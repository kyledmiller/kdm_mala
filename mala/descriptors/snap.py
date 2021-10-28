"""SNAP descriptor class."""
import os
import warnings
import time

import ase
import ase.io
try:
    from lammps import lammps
    from lammps import constants as lammps_constants
except ModuleNotFoundError:
    warnings.warn("You either don't have LAMMPS installed or it is not "
                  "configured correctly. Using SNAP descriptors "
                  "might still work, but trying to calculate SNAP "
                  "descriptors from atomic positions will crash.",
                  stacklevel=3)

from mala.descriptors.lammps_utils import *
from mala.descriptors.descriptor_base import DescriptorBase
from mala.common.parallelizer import get_comm

class SNAP(DescriptorBase):
    """Class for calculation and parsing of SNAP descriptors.

    Parameters
    ----------
    parameters : mala.common.parameters.Parameters
        Parameters object used to create this object.
    """

    def __init__(self, parameters):
        super(SNAP, self).__init__(parameters)
        self.in_format_ase = ""

    @staticmethod
    def convert_units(array, in_units="None"):
        """
        Convert the units of a SNAP descriptor.

        Since these do not really have units this function does nothing yet.

        Parameters
        ----------
        array : numpy.array
            Data for which the units should be converted.

        in_units : string
            Units of array.

        Returns
        -------
        converted_array : numpy.array
            Data in MALA units.
        """
        if in_units == "None":
            return array
        else:
            raise Exception("Unsupported unit for SNAP.")

    @staticmethod
    def backconvert_units(array, out_units):
        """
        Convert the units of a SNAP descriptor.

        Since these do not really have units this function does nothing yet.

        Parameters
        ----------
        array : numpy.array
            Data in MALA units.

        out_units : string
            Desired units of output array.

        Returns
        -------
        converted_array : numpy.array
            Data in out_units.
        """
        if out_units == "None":
            return array
        else:
            raise Exception("Unsupported unit for SNAP.")

    def calculate_from_qe_out(self, qe_out_file, qe_out_directory):
        """
        Calculate the SNAP descriptors based on a Quantum Espresso outfile.

        Parameters
        ----------
        qe_out_file : string
            Name of Quantum Espresso output file for snapshot.

        qe_out_directory : string
            Path to Quantum Espresso output file for snapshot.

        Returns
        -------
        snap_descriptors : numpy.array
            Numpy array containing the SNAP descriptors with the dimension
            (x,y,z,snap_dimension)

        """
        self.in_format_ase = "espresso-out"
        print("Calculating SNAP descriptors from", qe_out_file, "at",
              qe_out_directory)
        # We get the atomic information by using ASE.
        infile = os.path.join(qe_out_directory, qe_out_file)
        atoms = ase.io.read(infile, format=self.in_format_ase)

        # Enforcing / Checking PBC on the read atoms.
        atoms = self.enforce_pbc(atoms)

        # Get the grid dimensions.
        qe_outfile = open(infile, "r")
        lines = qe_outfile.readlines()
        nx = 0
        ny = 0
        nz = 0

        for line in lines:
            if "FFT dimensions" in line:
                tmp = line.split("(")[1].split(")")[0]
                nx = int(tmp.split(",")[0])
                ny = int(tmp.split(",")[1])
                nz = int(tmp.split(",")[2])
                break

        return self.__calculate_snap(atoms,
                                     qe_out_directory, [nx, ny, nz])

    def calculate_from_atoms(self, atoms, grid_dimensions,
                             working_directory="."):
        """
        Calculate the SNAP descriptors based on the atomic configurations.

        Parameters
        ----------
        atoms : ase.Atoms
            Atoms object holding the atomic configuration.l

        grid_dimensions : list
            Grid dimensions to be used, in the format [x,y,z].

        working_directory : string
            A directory in which to perform the LAMMPS calculation.

        Returns
        -------
        descriptors : numpy.array
            Numpy array containing the descriptors with the dimension
            (x,y,z,descriptor_dimension)
        """
        # Enforcing / Checking PBC on the input atoms.
        atoms = self.enforce_pbc(atoms)
        return self.__calculate_snap(atoms, working_directory, grid_dimensions)

    def gather_descriptors(self, snap_descriptors_np):
        # Gather all SNAP descriptors on rank 0.
        comm = get_comm()
        all_snap_descriptors = comm.gather(snap_descriptors_np, root=0)

    def __calculate_snap(self, atoms, outdir, grid_dimensions):
        """Perform actual SNAP calculation."""
        from lammps import lammps
        lammps_format = "lammps-data"
        ase_out_path = os.path.join(outdir, "lammps_input.tmp")
        ase.io.write(ase_out_path, atoms, format=lammps_format)

        # We also need to know how big the grid is.
        # Iterating directly through the file is slow, but the
        # grid information is at the top (around line 200).
        nx = None
        ny = None
        nz = None
        if len(self.dbg_grid_dimensions) == 3:
            nx = self.dbg_grid_dimensions[0]
            ny = self.dbg_grid_dimensions[1]
            nz = self.dbg_grid_dimensions[2]
        else:
            nx = grid_dimensions[0]
            ny = grid_dimensions[1]
            nz = grid_dimensions[2]

        # Build LAMMPS arguments from the data we read.
        lmp_cmdargs = ["-screen", "none", "-log", os.path.join(outdir,
                                                               "lammps_log.tmp")]
        lmp_cmdargs = set_cmdlinevars(lmp_cmdargs,
                                      {
                                        "ngridx": nx,
                                        "ngridy": ny,
                                        "ngridz": nz,
                                        "twojmax": self.parameters.twojmax,
                                        "rcutfac": self.parameters.rcutfac,
                                        "atom_config_fname": ase_out_path
                                      })

        # Build the LAMMPS object.
        lmp = lammps(cmdargs=lmp_cmdargs)

        # An empty string means that the user wants to use the standard input.
        # What that is differs depending on serial/parallel execution.
        if self.parameters.lammps_compute_file == "":
            filepath = __file__.split("snap")[0]
            if self.parameters._configuration["mpi"]:
                self.parameters.lammps_compute_file = \
                    os.path.join(filepath, "in.bgridlocal.python")
            else:
                self.parameters.lammps_compute_file = \
                    os.path.join(filepath, "in.bgrid.python")

        # Do the LAMMPS calculation.
        lmp.file(self.parameters.lammps_compute_file)

        # Set things not accessible from LAMMPS
        # First 3 cols are x, y, z, coords
        ncols0 = 3

        # Analytical relation for fingerprint length
        ncoeff = (self.parameters.twojmax+2) * \
                 (self.parameters.twojmax+3)*(self.parameters.twojmax+4)
        ncoeff = ncoeff // 24   # integer division
        self.fingerprint_length = ncols0+ncoeff

        # Extract data from LAMMPS calculation.
        # This is different for the parallel and the serial case.
        # In the serial case we can expect to have a full SNAP array at the
        # end of this function.
        # This is not necessarily true for the parallel case.

        if self.parameters._configuration["mpi"]:
            nrows_local = extract_compute_np(lmp, "bgridlocal",
                                             lammps_constants.LMP_STYLE_LOCAL,
                                             lammps_constants.LMP_SIZE_ROWS)
            ncols_local = extract_compute_np(lmp, "bgridlocal",
                                             lammps_constants.LMP_STYLE_LOCAL,
                                             lammps_constants.LMP_SIZE_COLS)
            print(nrows_local, ncols_local)
            if ncols_local != self.fingerprint_length + 3:
                raise Exception("Inconsistent number of features.")

            snap_descriptors_np = \
                extract_compute_np(lmp, "bgridlocal",
                                   lammps_constants.LMP_STYLE_LOCAL, 2,
                                   array_shape=(nrows_local, ncols_local))
        else:
            # Extract data from LAMMPS calculation.
            snap_descriptors_np = \
                extract_compute_np(lmp, "bgrid", 0, 2,
                                   (nz, ny, nx, self.fingerprint_length))
            # switch from x-fastest to z-fastest order (swaps 0th and 2nd
            # dimension)
            snap_descriptors_np = snap_descriptors_np.transpose([2, 1, 0, 3])

        return snap_descriptors_np

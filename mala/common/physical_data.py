"""Base class for all calculators that deal with physical data"""
from abc import ABC, abstractmethod

import json
import numpy as np
import openpmd_api as io


class PhysicalData(ABC):
    """
    Base class for physical data.

    Implements general framework to read and write such data to and from
    files.
    """

    ##############################
    # Constructors
    ##############################

    def __init__(self, parameters):
        self.parameters = parameters
        self.granularity = self.parameters.data.openpmd_granularity

    ##############################
    # Properties
    ##############################

    @property
    @abstractmethod
    def data_name(self):
        """Get a string that describes the data (for e.g. metadata)."""
        pass

    @property
    @abstractmethod
    def si_dimension(self):
        """
        Dictionary containing the SI unit dimensions in OpenPMD format

        Needed for OpenPMD interface.
        """
        pass

    @property
    @abstractmethod
    def si_unit_conversion(self):
        """
        Numeric value of the conversion from MALA (ASE) units to SI.

        Needed for OpenPMD interface.
        """
        pass

    ##############################
    # Read functions.
    #   Write functions for now not implemented at this level
    #   because there is no need to.
    ##############################

    def read_from_numpy_file(self, path, units=None, array=None):
        """
        Read the data from a numpy file.

        Parameters
        ----------
        path : string
            Path to the numpy file.

        units : string
            Units the data is saved in.

        array : np.ndarray
            If not None, the array to save the data into.
            The array has to be 4-dimensional.

        Returns
        -------
        data : numpy.ndarray or None
            If array is None, a numpy array containing the data.
            Elsewise, None, as the data will be saved into the provided
            array.

        """
        if array is None:
            loaded_array = np.load(path)[:, :, :, self._feature_mask():]
            self._process_loaded_array(loaded_array, units=units)
            return loaded_array
        else:
            array[:, :, :, :] = np.load(path)[:, :, :, self._feature_mask():]
            self._process_loaded_array(array, units=units)

    def read_from_openpmd_file(self, path, units=None, array=None):
        """
        Read the data from a numpy file.

        Parameters
        ----------
        path : string
            Path to the openPMD file.

        units : string
            Units the data is saved in.

        array : np.ndarray
            If not None, the array to save the data into.
            The array has to be 4-dimensional.

        Returns
        -------
        data : numpy.ndarray or None
            If array is None, a numpy array containing the data.
            Elsewise, None, as the data will be saved into the provided
            array.
        """
        series = io.Series(path, io.Access.read_only,
                           options=json.dumps(
                                {"defer_iteration_parsing": True} |
                                self.parameters.
                                    _configuration["openpmd_configuration"]))

        # Check if this actually MALA compatible data.
        if series.get_attribute("is_mala_data") != 1:
            raise Exception("Non-MALA data detected, cannot work with this "
                            "data.")

        # A bit clanky, but this way only the FIRST iteration is loaded,
        # which is what we need for loading from a single file that
        # may be whatever iteration in its series.
        # Also, in combination with `defer_iteration_parsing`, specified as
        # default above, this opens and parses the first iteration,
        # and no others.
        for current_iteration in series.read_iterations():
            mesh = current_iteration.meshes[self.data_name]
            break

        # TODO: Are there instances in MALA, where we wouldn't just label
        # the feature dimension with 0,1,... ? I can't think of one.
        # But there may be in the future, and this'll break
        if array is None:
            data = np.zeros((mesh["0"].shape[0], mesh["0"].shape[1],
                             mesh["0"].shape[2], len(mesh)-self._feature_mask()),
                            dtype=mesh["0"].dtype)
        else:
            if array.shape[0] != mesh["0"].shape[0] or \
               array.shape[1] != mesh["0"].shape[1] or \
               array.shape[2] != mesh["0"].shape[2] or \
               array.shape[3] != len(mesh)-self._feature_mask():
                raise Exception("Cannot load data into array, wrong "
                                "shape provided.")

        # Only check this once, since we do not save arrays with different
        # units throughout the feature dimension.
        # Later, we can merge this unit check with the unit conversion
        # MALA does naturally.
        if not np.isclose(mesh[str(0)].unit_SI, self.si_unit_conversion):
            raise Exception("MALA currently cannot operate with OpenPMD "
                            "files with non-MALA units.")
                            
        # Deal with `granularity` items of the vectors at a time
        # Or in the openPMD layout: with `granularity` record components
        if array is None:
            array_shape = data.shape
            data_type = data.dtype
        else:
            array_shape = array.shape
            data_type = array.dtype
        for base in range(self._feature_mask(), array_shape[3]+self._feature_mask(),
                          self.granularity):
            end = min(base + self.granularity, array_shape[3]+self._feature_mask())
            transposed = np.empty(
                (end - base, array_shape[0], array_shape[1], array_shape[2]),
                dtype=data_type)
            for i in range(base, end):
                # transposed[i - base, :, :, :] = mesh[str(i)][:, :, :]
                mesh[str(i)].load_chunk(transposed[i - base, :, :, :])
            series.flush()
            if array is None:
                data[:, :, :, base-self._feature_mask():end-self._feature_mask()] \
                    = np.transpose(transposed, axes=[1, 2, 3, 0])[:, :, :, :]
            else:
                array[:, :, :, base-self._feature_mask():end-self._feature_mask()] \
                    = np.transpose(transposed, axes=[1, 2, 3, 0])[:, :, :, :]

        if array is None:
            self._process_loaded_array(data, units=units)
            return data
        else:
            self._process_loaded_array(array, units=units)

    def read_dimensions_from_numpy_file(self, path):
        """
        Read only the dimensions from a numpy file.

        Parameters
        ----------
        path : string
            Path to the numpy file.
        """
        loaded_array = np.load(path, mmap_mode="r")
        return self._process_loaded_dimensions(np.shape(loaded_array))

    def read_dimensions_from_openpmd_file(self, path):
        """
        Read only the dimensions from a openPMD file.

        Parameters
        ----------
        path : string
            Path to the openPMD file.
        """
        series = io.Series(path, io.Access.read_only,
                           options=json.dumps(
                                {"defer_iteration_parsing": True} |
                                self.parameters.
                                    _configuration["openpmd_configuration"]))

        # Check if this actually MALA compatible data.
        if series.get_attribute("is_mala_data") != 1:
            raise Exception("Non-MALA data detected, cannot work with this "
                            "data.")

        # A bit clanky, but this way only the FIRST iteration is loaded,
        # which is what we need for loading from a single file that
        # may be whatever iteration in its series.
        # Also, in combination with `defer_iteration_parsing`, specified as
        # default above, this opens and parses the first iteration,
        # and no others.
        for current_iteration in series.read_iterations():
            mesh = current_iteration.meshes[self.data_name]
            return self.\
                _process_loaded_dimensions((mesh["0"].shape[0],
                                            mesh["0"].shape[1],
                                            mesh["0"].shape[2],
                                            len(mesh)))

    def write_to_numpy_file(self, path, array):
        """
        Write data to a numpy file.

        Parameters
        ----------
        path : string
            File to save into.

        array : numpy.ndarray
            Array to save.
        """
        np.save(path, array)

    def write_to_openpmd_iteration(self, iteration, array):
        """
        Write a file within an OpenPMD iteration.

        Parameters
        ----------
        iteration : OpenPMD iteration
            OpenPMD iteration into which to save.

        array : numpy.ndarry
            Array to save.

        """
        mesh = iteration.meshes[self.data_name]
        self._set_openpmd_attribtues(mesh)
        dataset = io.Dataset(array.dtype,
                             array[:, :, :, 0].shape)

        # See above - will currently break for density of states,
        # which is something we never do though anyway.
        # Deal with `granularity` items of the vectors at a time
        # Or in the openPMD layout: with `granularity` record components
        granularity = 16 # just some random value for now
        for base in range(0, array.shape[3], granularity):
            end = min(base + granularity, array.shape[3])
            transposed = \
                np.transpose(array[:, :, :, base:end], axes=[3, 0, 1, 2]).copy()
            for i in range(base, end):
                mesh_component = mesh[str(i)]
                mesh_component.reset_dataset(dataset)

                # mesh_component[:, :, :] = transposed[i - base, :, :, :]
                mesh_component.store_chunk(transposed[i - base, :, :, :])

                # All data is assumed to be saved in
                # MALA units, so the SI conversion factor we save
                # here is the one for MALA (ASE) units
                mesh_component.unit_SI = self.si_unit_conversion
                # position: which relative point within the cell is
                # represented by the stored values
                # ([0.5, 0.5, 0.5] represents the middle)
                mesh_component.position = [0.5, 0.5, 0.5]
            iteration.series_flush()

        iteration.close(flush=True)

    ##############################
    # Class-specific reshaping, processing, etc. of data.
    #    Has to be implemented by the classes themselves. E.g. descriptors may
    #    need to cut xyz-coordinates, LDOS/density may need unit conversion.
    ##############################

    @abstractmethod
    def _process_loaded_array(self, array, units=None):
        pass

    @abstractmethod
    def _process_loaded_dimensions(self, array_dimensions):
        pass

    def _feature_mask(self):
        return 0

    def _set_geometry_info(self, mesh):
        pass

    def _set_openpmd_attribtues(self, mesh):
        mesh.unit_dimension = self.si_dimension
        mesh.axis_labels = ["x", "y", "z"]
        mesh.grid_global_offset = [0, 0, 0]

        # MALA internally operates in Angstrom (10^-10 m)
        mesh.grid_unit_SI = 1e-10

        mesh.comment = \
            "This is a special geometry, " \
            "based on the cartesian geometry."

        # Fill geometry information (if provided)
        self._set_geometry_info(mesh)


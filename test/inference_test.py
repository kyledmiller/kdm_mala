import importlib
import os

import pytest
import numpy as np
from mala import Parameters, DataHandler, DataScaler, Network, Tester, \
                 Trainer, Predictor, LDOS, Runner

from mala.datahandling.data_repo import data_repo_path
data_path = os.path.join(data_repo_path, "Be2")
param_path = os.path.join(data_repo_path, "workflow_test/")
accuracy_strict = 1e-16
accuracy_coarse = 5e-7
accuracy_very_coarse = 3


class TestInference:
    """Tests several inference/accuracy related parts."""

    def test_unit_conversion(self):
        """Test that RAM inexpensive unit conversion works."""
        parameters, network, data_handler = Runner.load_run("workflow_test",
                                                            zip_run=False,
                                                            load_runner=False,
                                                            path=param_path)
        parameters.data.use_lazy_loading = False
        parameters.running.mini_batch_size = 50

        data_handler.clear_data()
        data_handler.add_snapshot("Be_snapshot0.in.npy", data_path,
                                            "Be_snapshot0.out.npy", data_path,
                                            "te")

        data_handler.prepare_data()

        # Confirm that unit conversion does not introduce any errors.

        from_file_1 = data_handler.target_calculator.\
            convert_units(np.load(os.path.join(data_path, "Be_snapshot" +
                                               str(0) + ".out.npy")),
                          in_units="1/(eV*Bohr^3)")
        from_file_2 = np.load(os.path.join(data_path, "Be_snapshot" + str(0) +
                                           ".out.npy"))\
            * data_handler.target_calculator.convert_units(1, in_units="1/(eV*Bohr^3)")

        assert from_file_1.sum() == from_file_2.sum()

    def test_inference_ram(self):
        """
        Test inference accuracy (for RAM based trainings).

        What is explicitly tested is that the scaling and rescaling do not
        change the values too drastically. During inference (or at least
        in the test case) this is done.
        """
        # Without lazy loading, there is a bigger numerical error in the actual
        # outputs. This is due to the fact that we scale and rescale data on 32
        # byte float arrays; lazy loading is therefore drastically advised for
        # inference/testing purposes.
        batchsizes = [46, 99, 500, 1977]
        for batchsize in batchsizes:
            actual_ldos, from_file, predicted_ldos, raw_predicted_outputs  =\
            self.__run(use_lazy_loading=False, batchsize=batchsize)
            assert np.isclose(actual_ldos.sum(), from_file.sum(),
                              atol=accuracy_coarse)

    def test_inference_lazy_loading(self):
        """
        Test inference accuracy (for lazy loading based trainings).

        What is explicitly tested is that the scaling and rescaling do not
        change the values too drastically. During inference (or at least
        in the test case) this is done.
        """
        # Without lazy loading, there is a bigger numerical error in the actual
        # outputs. This is due to the fact that we scale and rescale data on 32
        # byte float arrays; lazy loading is therefore drastically advised for
        # inference/testing purposes.
        batchsizes = [46, 99, 500, 1977]
        for batchsize in batchsizes:
            actual_ldos, from_file, predicted_ldos, raw_predicted_outputs = \
                self.__run(use_lazy_loading=True, batchsize=batchsize)
            assert np.isclose(actual_ldos.sum(), from_file.sum(),
                              atol=accuracy_strict)

    @staticmethod
    def __run(use_lazy_loading=False, batchsize=46):
        # First we load Parameters and network.
        parameters, network, data_handler, tester = \
            Tester.load_run("workflow_test", path=param_path, zip_run=False)
        parameters.data.use_lazy_loading = use_lazy_loading
        parameters.running.mini_batch_size = batchsize

        data_handler.clear_data()
        data_handler.add_snapshot("Be_snapshot0.in.npy", data_path,
                                  "Be_snapshot0.out.npy", data_path,
                                  "te")
        data_handler.add_snapshot("Be_snapshot1.in.npy", data_path,
                                  "Be_snapshot1.out.npy", data_path,
                                  "te")

        data_handler.prepare_data()

        # Get values with current framework.
        actual_ldos, predicted_ldos = tester.predict_targets(0)

        # Compare actual_ldos with file directly.
        # This is the only comparison that counts.
        from_file = np.load(os.path.join(data_path, "Be_snapshot" + str(0) +
                                         ".out.npy"))

        # Test if prediction still works.
        raw_predicted_outputs = np.load(os.path.join(data_path, "Be_snapshot" +
                                                     str(0) + ".in.npy"))
        raw_predicted_outputs = data_handler.\
            raw_numpy_to_converted_scaled_tensor(raw_predicted_outputs,
                                                 "in", "None")
        raw_predicted_outputs = network.\
            do_prediction(raw_predicted_outputs)
        raw_predicted_outputs = data_handler.output_data_scaler.\
            inverse_transform(raw_predicted_outputs, as_numpy=True)

        return actual_ldos, from_file, predicted_ldos, raw_predicted_outputs


import hashlib
import logging
from datetime import datetime

import numpy as np
from matplotlib import pyplot as plt
from scipy.ndimage import gaussian_filter1d, gaussian_filter
from scipy.optimize import nnls
from skimage.restoration import rolling_ball
from sklearn.decomposition import PCA, NMF

from contents.custom_pyqt_objects import ImageViewYX
from contents import nnls_pytorch
from contents import torch_nmf

d_type = '16bit'

logger = logging.getLogger(__name__)

class MultivariateAnalyzer(object):
    def __init__(self, data, n_components, wavenumbers, method='NNMF'):
        self.resonance_data_zyx = None
        self.full_W_seed = False
        self.H_weighted_W_seed = False
        self.avg_W_seed = False
        self.w_seed_mode = 'nnls'
        self.custom_nnmf_init:bool = False
        self.spectral_info = None
        self.wavenumbers = None
        self.seed_W = None
        self.seed_H = None
        self.seed_H_background_flag = None
        self.pca_ready = None
        self.PCs = None
        self.pca_2DX = None
        self.pca_X = None
        self._n_components = None
        self.pca_data_std = None
        self.seed_pixels = None
        self.fixed_W_2D = None
        self.fixed_W = None
        self.fixed_H = None
        self._W_prepared = False
        self.raw_data_3d = None
        self.data_2d = None
        self.prepared = None
        self.resonance_data_2d = None
        self.analysis_method = method
        self.nnmf_solver = 'mu'
        self.nnmf_backend_preference = 'auto'
        self.prefer_torch_nmf = True
        self.torch_nmf_max_iter = 5000
        self.torch_nmf_tol = 1e-4
        self.prefer_torch_nnls = True
        self.torch_nnls_max_iter = 250
        self.torch_nnls_tol = 1e-4
        self.torch_nnls_chunk_size = 32768
        self._nnls_abundance_cache = {}
        self.update_image_data(data, n_components, wavenumbers)

    def update_spectral_info(self, spectral_info: list[dict[str, float | int]]):
        self.spectral_info = spectral_info
        logger.info(f'MV Anaylzer: Updated spectral info: {self.spectral_info}')
        self._W_prepared = False

    def _clear_nnls_abundance_cache(self):
        self._nnls_abundance_cache = {}

    def update_image_data(self, data: np.ndarray, n_components: int, wavenumbers: np.ndarray):
        self.prepared = False
        self.raw_data_3d = data
        if data is not None:
            self.resonance_data_zyx = data[...]
        self.fixed_H = None
        self.fixed_W = None
        # 2D equivalent with spectral slices at axis 0
        self.fixed_W_2D = None
        self.seed_pixels = None
        self.pca_data_std = None
        self._n_components = n_components
        self.pca_X = None
        self.pca_2DX = None  # reshaped 2D PCA image data
        self.PCs = None
        self.pca_ready = False
        self.seed_H = None
        self.seed_H_background_flag = None
        self.seed_W = None
        self._W_prepared = False
        self.avg_W_seed = False
        self.full_W_seed = False
        self.H_weighted_W_seed = False
        self.w_seed_mode = 'nnls'
        self._clear_nnls_abundance_cache()
        self.wavenumbers = wavenumbers
        if self.raw_data_3d is not None:
            logger.info(f'{self.raw_data_3d.shape=}')
            self.standardize_and_reshape_data()
        else:
            logger.warning('No data provided to the MV analyzer')

    def update_wavenumbers(self, wavenumbers):
        # TODO: in future also update the results then? If analysis is fast enough
        self.wavenumbers = wavenumbers

    def update_resonance_image_data(self, data: np.ndarray):
        logger.info('Updated resonance/subtracted data in the MV analyzer')
        self._clear_nnls_abundance_cache()
        # check if the emitted data is non-empty
        if data.size:
            self.resonance_data_zyx = data
            if self.resonance_data_zyx.ndim == 3:
                # move spectral axis to final axis
                self.resonance_data_2d = np.moveaxis(self.resonance_data_zyx, 0, -1)
                # reshape to 2d for analysis, concatenate the spatial info along the first axis
                self.resonance_data_2d = self.resonance_data_2d.reshape(-1, self.raw_data_3d.shape[0])
            return
        logger.warning('No subtraction data available, restoring original data')
        self.resonance_data_2d = self.data_2d
        self.resonance_data_zyx = self.raw_data_3d
        # recalc seeds?

    def get_n_components(self):
        return self._n_components

    def update_components(self, n_components):
        self._n_components = n_components
        self._clear_nnls_abundance_cache()
        if self.seed_H is not None:
            if self.seed_H.shape[0] < n_components:
                # Add rows of ones to the seed matrix
                new_rows = n_components - self.seed_H.shape[0]
                self.seed_H = np.vstack((self.seed_H, np.zeros((new_rows, self.raw_data_3d.shape[0])))
                                        )
                self.seed_H_background_flag = np.hstack((self.seed_H_background_flag, np.zeros(new_rows, dtype=bool)))
            else:
                self.seed_H = self.seed_H[:n_components, ...]
                self.seed_H_background_flag = self.seed_H_background_flag[:n_components]

    def set_custom_nnmf_init(self, state):
        self.custom_nnmf_init = state

    def set_nnmf_solver(self, solver: str):
        solver = (solver or 'mu').strip().lower()
        if solver not in {'cd', 'mu'}:
            raise ValueError(f"Unsupported NMF solver '{solver}'. Expected 'cd' or 'mu'.")
        self.nnmf_solver = solver
        logger.info("NNMF solver updated to %s", self.nnmf_solver)

    def set_nnmf_backend_preference(self, mode: str):
        mode = (mode or 'auto').strip().lower()
        if mode not in {'auto', 'cpu', 'gpu'}:
            raise ValueError(f"Unsupported NMF backend preference '{mode}'. Expected 'auto', 'cpu', or 'gpu'.")
        self.nnmf_backend_preference = mode
        logger.info("NNMF backend preference updated to %s", self.nnmf_backend_preference)

    def _resolve_torch_nmf_device(self) -> str | None:
        """
        Find the best available device for PyTorch NMF based on user preference and availability.
        If user prefers GPU but it's unavailable, falls back to CPU with a warning. If PyTorch is unavailable, returns None.
        If auto and GPU is available, returns 'cuda', otherwise 'cpu'.
        """
        if not self.prefer_torch_nmf:
            return None

        if self.nnmf_backend_preference == 'cpu':
            return None

        if not torch_nmf.torch_available():
            return None

        if self.nnmf_backend_preference == 'gpu':
            if torch_nmf.cuda_available():
                return 'cuda'
            logger.info("NNMF backend is set to prefer GPU, but CUDA is unavailable. Falling back to CPU.")
            return 'cpu'

        if torch_nmf.cuda_available():
            return 'cuda'
        return 'cpu'

    def _run_torch_mu_nmf(
            self,
            data: np.ndarray,
            *,
            w_init: np.ndarray | None = None,
            h_init: np.ndarray | None = None,
            device: str | None = None,
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """
        Run multiplicative updates NMF using the PyTorch backend
        """
        device = device or self._resolve_torch_nmf_device()
        if device is None:
            raise RuntimeError("PyTorch NMF backend is not available.")
        logger.info("Running PyTorch MU-NMF on %s.", device)
        return torch_nmf.solve_nmf_multiplicative_updates(
            data,
            n_components=self._n_components,
            w_init=w_init,
            h_init=h_init,
            device=device,
            max_iter=self.torch_nmf_max_iter,
            tol=self.torch_nmf_tol,
            eps=getattr(self, "nnmf_epsilon", 1e-8),
            seed=0,
        )

    def _fit_nmf_backend(
            self,
            data: np.ndarray,
            *,
            init: str,
            w_init: np.ndarray | None = None,
            h_init: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """
        Fit NMF to the data using the specified solver and backend preferences.
         - If multiplicative updates (MU) solver is selected and PyTorch backend is available, it will attempt to use it.
         - If PyTorch MU fails for any reason, it will log the error and fall back to scikit-learn's MU implementation.
         - For coordinate descent (CD) solver or if CPU backend is preferred, it will use scikit-learn's implementation directly.
         - Returns the factorized matrices W and H, along with an info dictionary containing metadata about the fit.
         - The info dictionary includes the backend used, solver type, number of iterations, and model parameters.
         - This method ensures that the best available computational resources are utilized while providing robust fallbacks.
         - The input data is converted to float32 for compatibility with both backends.
         - Custom initializations for W and H can be provided when using the 'custom' init mode.
         - The method handles exceptions gracefully, ensuring that a failure in one backend does not prevent analysis from proceeding.
         - Logging is used extensively to inform about which backend is being used and any issues encountered.
        """
        data_f32 = np.asarray(data, dtype=np.float32)

        torch_device = self._resolve_torch_nmf_device() if self.nnmf_solver == 'mu' else None
        if self.nnmf_solver == 'mu' and torch_device is not None:
            # early return if PyTorch MU-NMF succeeds, otherwise log and fall back to CPU MU or CD as needed
            try:
                fixed_W, fixed_H, info = self._run_torch_mu_nmf(
                    data_f32,
                    w_init=w_init,
                    h_init=h_init,
                    device=torch_device,
                )
                info = dict(info)
                info["backend"] = "torch"
                return fixed_W, fixed_H, info
            except Exception as exc:
                if torch_nmf.import_error() is not None and not torch_nmf.torch_available():
                    logger.info("PyTorch NMF unavailable; using scikit-learn MU fallback. Reason: %s", torch_nmf.import_error())
                else:
                    logger.warning("PyTorch NMF failed; falling back to scikit-learn MU. Error: %s", exc)
        elif self.nnmf_solver == 'mu' and self.nnmf_backend_preference == 'cpu':
            logger.info("NNMF backend preference is CPU only; using scikit-learn MU backend.")
        # ====
        # CPU fallback for MU or CD solver
        # For 'cd' solver or if CPU backend is preferred, use scikit-learn's implementation directly
        nnmf_model = NMF(
            n_components=self._n_components,
            init=init,
            random_state=0,
            max_iter=1000,
            solver=self.nnmf_solver,
        )
        if init == 'custom':
            fixed_W = nnmf_model.fit_transform(
                data_f32,
                H=np.asarray(h_init, dtype=np.float32),
                W=np.asarray(w_init, dtype=np.float32),
            )
        else:
            fixed_W = nnmf_model.fit_transform(data_f32)
        fixed_H = nnmf_model.components_
        info = {
            "backend": "sklearn",
            "solver": self.nnmf_solver,
            "n_iter": int(nnmf_model.n_iter_),
            "params": nnmf_model.get_params(),
        }
        return fixed_W, fixed_H, info

    @staticmethod
    def _has_seed_signal(spectrum: np.ndarray | None, eps: float = 1e-8) -> bool:
        if spectrum is None:
            return False
        arr = np.asarray(spectrum, dtype=float)
        if arr.size == 0:
            return False
        finite = np.isfinite(arr)
        if not np.any(finite):
            return False
        return np.any(np.abs(arr[finite]) > eps)

    @staticmethod
    def _prepare_seed_spectrum(spectrum: np.ndarray, eps: float = 1e-8) -> np.ndarray | None:
        arr = np.asarray(spectrum, dtype=np.float64)
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        min_val = float(np.min(arr))
        if min_val < 0:
            arr = arr - min_val
        arr = np.maximum(arr, 0.0)
        norm = float(np.linalg.norm(arr))
        if norm <= eps:
            return None
        return arr / norm

    def _component_prefers_subtracted_data(self, component_index: int, bgd: bool = False) -> bool:
        if bgd:
            return False
        info_list = self.get_sepctral_info_component(component_index)
        if not info_list:
            return True
        return any(bool(info.get('Use subtracted data', True)) for info in info_list)

    def _get_image_data_for_component(self, component_index: int, bgd: bool = False) -> np.ndarray:
        image_data, _ = self._get_image_data_and_source_key(component_index, bgd=bgd)
        return image_data

    def _get_image_data_and_source_key(self, component_index: int, bgd: bool = False) -> tuple[np.ndarray, str]:
        if not self._component_prefers_subtracted_data(component_index, bgd=bgd):
            logger.info('Component %s uses raw data for W seed estimation.', component_index)
            return self.data_2d, 'raw'
        if bgd:
            logger.info('Background component! Using raw data for W seed estimation.')
            return self.data_2d, 'raw'
        logger.info('Using subtracted data for W seed estimation from H.')
        return self.resonance_data_2d, 'subtracted'

    def _get_seed_basis(self, eps: float = 1e-8) -> tuple[np.ndarray, dict[int, int]]:
        if self.seed_H is None:
            return np.empty((self.raw_data_3d.shape[0], 0), dtype=np.float64), {}

        basis_columns = []
        component_to_basis = {}
        for component_index in range(self.seed_H.shape[0]):
            spectrum = self.seed_H[component_index]
            if not self._has_seed_signal(spectrum, eps=eps):
                continue
            prepared = self._prepare_seed_spectrum(spectrum, eps=eps)
            if prepared is None:
                continue
            component_to_basis[component_index] = len(basis_columns)
            basis_columns.append(prepared)

        if not basis_columns:
            return np.empty((self.raw_data_3d.shape[0], 0), dtype=np.float64), {}
        return np.column_stack(basis_columns), component_to_basis

    @staticmethod
    def _project_target_strength(image_data: np.ndarray, prepared_target: np.ndarray) -> np.ndarray:
        working_data = np.asarray(image_data, dtype=np.float64)
        working_data = np.nan_to_num(working_data, nan=0.0, posinf=0.0, neginf=0.0)
        working_data = np.maximum(working_data, 0.0)
        return np.maximum(working_data @ prepared_target, 0.0)

    @staticmethod
    def _make_nnls_cache_key(
            basis: np.ndarray,
            component_to_basis: dict[int, int],
            source_key: str,
            n_pixels: int,
            backend_name: str,
    ) -> tuple:
        basis_components = tuple(
            component for component, _ in sorted(component_to_basis.items(), key=lambda item: item[1])
        )
        basis_bytes = np.ascontiguousarray(basis, dtype=np.float64).view(np.uint8)
        basis_hash = hashlib.sha1(basis_bytes).hexdigest()
        return source_key, n_pixels, basis.shape, basis_components, basis_hash, backend_name

    def _nnls_backend_name(self) -> str:
        if self.prefer_torch_nnls and nnls_pytorch.cuda_available():
            return 'torch-cuda'
        return 'scipy-cpu'

    def _build_scipy_nnls_abundance_matrix(
            self,
            image_data: np.ndarray,
            basis: np.ndarray,
            eps: float,
    ) -> np.ndarray:
        working_data = np.asarray(image_data, dtype=np.float64)
        working_data = np.nan_to_num(working_data, nan=0.0, posinf=0.0, neginf=0.0)
        working_data = np.maximum(working_data, 0.0)

        abundance = np.full((working_data.shape[0], basis.shape[1]), eps, dtype=np.float32)
        active_pixels = np.where(np.any(working_data > eps, axis=1))[0]
        logger.info(
            'Running SciPy NNLS abundance solve on %s active pixels with %s seed spectra.',
            active_pixels.size,
            basis.shape[1],
        )
        for pixel_index in active_pixels:
            coeffs, _ = nnls(basis, working_data[pixel_index])
            abundance[pixel_index] = np.maximum(coeffs, eps)
        return abundance

    def _build_nnls_abundance_matrix(
            self,
            image_data: np.ndarray,
            basis: np.ndarray,
            eps: float,
            source_key: str,
    ) -> np.ndarray:
        if basis.shape[1] == 1:
            working_data = np.asarray(image_data, dtype=np.float64)
            working_data = np.nan_to_num(working_data, nan=0.0, posinf=0.0, neginf=0.0)
            working_data = np.maximum(working_data, 0.0)
            denom = float(np.dot(basis[:, 0], basis[:, 0])) + eps
            abundance = np.full((working_data.shape[0], 1), eps, dtype=np.float32)
            abundance[:, 0] = np.maximum((working_data @ basis[:, 0]) / denom, eps).astype(np.float32)
            return abundance

        if self.prefer_torch_nnls and nnls_pytorch.cuda_available():
            try:
                logger.info('Using PyTorch CUDA NNLS solver for %s data.', source_key)
                abundance = nnls_pytorch.solve_batched_nnls_projected_gradient(
                    image_data,
                    basis,
                    device='cuda',
                    max_iter=self.torch_nnls_max_iter,
                    tol=self.torch_nnls_tol,
                    eps=eps,
                    chunk_size=self.torch_nnls_chunk_size,
                )
                return np.maximum(abundance, eps).astype(np.float32, copy=False)
            except Exception as exc:
                logger.warning('PyTorch CUDA NNLS solver failed; falling back to SciPy NNLS. Error: %s', exc)

        if self.prefer_torch_nnls and not nnls_pytorch.cuda_available():
            if nnls_pytorch.torch_available():
                logger.info('PyTorch is available but CUDA is not. Using SciPy NNLS fallback.')
            elif nnls_pytorch.import_error() is not None:
                logger.debug('PyTorch import unavailable: %s', nnls_pytorch.import_error())

        return self._build_scipy_nnls_abundance_matrix(image_data, basis, eps)

    def _get_cached_nnls_abundance_matrix(
            self,
            image_data: np.ndarray,
            basis: np.ndarray,
            component_to_basis: dict[int, int],
            eps: float,
            source_key: str,
    ) -> np.ndarray:
        backend_name = self._nnls_backend_name()
        cache_key = self._make_nnls_cache_key(
            basis,
            component_to_basis,
            source_key,
            image_data.shape[0],
            backend_name,
        )
        cached = self._nnls_abundance_cache.get(cache_key)
        if cached is not None and cached.shape == (image_data.shape[0], basis.shape[1]):
            logger.info('Reusing cached NNLS abundance matrix for %s data (%s).', source_key, backend_name)
            return cached

        abundance = self._build_nnls_abundance_matrix(image_data, basis, eps, source_key)
        self._nnls_abundance_cache[cache_key] = abundance
        return abundance

    def _estimate_selective_score_map(
            self,
            image_data: np.ndarray,
            component_index: int,
            prepared_target: np.ndarray,
            eps: float
    ) -> np.ndarray:
        working_data = np.asarray(image_data, dtype=np.float64)
        working_data = np.nan_to_num(working_data, nan=0.0, posinf=0.0, neginf=0.0)
        working_data = np.maximum(working_data, 0.0)
        target_strength = np.maximum(working_data @ prepared_target, 0.0)
        basis, component_to_basis = self._get_seed_basis(eps=eps)

        if basis.shape[1] <= 1 or component_index not in component_to_basis:
            logger.info('Selective score map for component %s falls back to target projection (no competitors).',
                        component_index)
            return np.maximum(target_strength, eps)

        target_basis_index = component_to_basis[component_index]
        competitor_indices = [idx for idx in range(basis.shape[1]) if idx != target_basis_index]
        competitor_strength = np.max(working_data @ basis[:, competitor_indices], axis=1)
        selectivity = target_strength / (target_strength + competitor_strength + eps)
        score_map = target_strength * selectivity
        return np.maximum(score_map, eps)

    def _estimate_nnls_abundance_map(
            self,
            image_data: np.ndarray,
            component_index: int,
            prepared_target: np.ndarray,
            eps: float,
            source_key: str,
    ) -> np.ndarray:
        basis, component_to_basis = self._get_seed_basis(eps=eps)
        if component_index not in component_to_basis:
            logger.info('NNLS abundance map for component %s falls back to target projection (target basis missing).',
                        component_index)
            return np.maximum(self._project_target_strength(image_data, prepared_target), eps)

        target_basis_index = component_to_basis[component_index]
        abundance = self._get_cached_nnls_abundance_matrix(
            image_data,
            basis,
            component_to_basis,
            eps,
            source_key,
        )
        return np.maximum(abundance[:, target_basis_index], eps)

    def standardize_and_reshape_data(self):
        """
        Perform  standardization on the (3D) imaging data for mean and standard deviation.
        Sets the mean value of each frame to 0 and the std to unity as required by many algorithms (e.g. PCA)
        """
        # Reshape the 3D hyperspectral array to a 2D array where the spatial info
        # is stored along the first axis and spectral info along the last...

        # Important: Spectral slices must always be in the last axis... This is contrary to what normal HS tiff files
        # are ordered. For that reasons we must first move the axes and then reshape the array
        raw_data_reordered = np.moveaxis(self.raw_data_3d, 0, -1)
        # Now we can reshape, where we leave the last axis untouched and only concatenate the fist two dimensions
        self.data_2d = raw_data_reordered.reshape(-1, self.raw_data_3d.shape[0]).astype(np.float32)
        self.resonance_data_2d = self.data_2d
        logger.info(f'{self.data_2d.shape = }')
        n_frames = self.data_2d.shape[1]
        standardized_data = np.zeros_like(self.data_2d)

        # standardize each image slice (each frame taken at a specific wavenumber)
        for i in range(n_frames):
            frame_data = self.data_2d[:, i]
            frame_mean = np.nanmean(frame_data, axis=None)
            # Subtract mean from data for std calculation as this will also scale the
            # matrix with subtracted mean
            frame_std = np.std(frame_data - frame_mean)
            frame_zero_mean_unity_std = (frame_data - frame_mean) / frame_std
            standardized_data[:, i] = frame_zero_mean_unity_std
        self.pca_data_std = standardized_data
        self.prepared = True

    def start_analysis(self):
        if self.analysis_method == 'PCA':
            logger.info('Starting PCA')
            self.PCA()
        elif self.analysis_method == 'NNMF':
            logger.info('Starting NNMF')
            logger.info(f'{self.custom_nnmf_init = }')
            if self.custom_nnmf_init:
                self.NNMF(skip_seed_fining=True)
            else:
                self.randomNNMF()

    def PCA(self):
        pca = PCA()
        nans = np.isnan(self.pca_data_std).any(axis=0)  # Check for NaN values along columns
        nan_cols = np.where(nans)[0]  # Get the indices of columns containing NaN values

        if nan_cols.size > 0:
            logger.info("PCA: NaN values in standardized data matrix in columns {}!".format(nan_cols))
            # Remove columns containing NaN values
            pca_data_cleared = self.pca_data_std[:, ~nans]

            # Update other relevant attributes if needed
            # self.wavenumber_cleared = np.delete(self.wavenumber_range, nan_cols)

            logger.info("PCA: Data matrix cleared of columns with NaN values. Ready for PCA analysis!")
        else:
            pca_data_cleared = self.pca_data_std
            logger.info("PCA: No NaN values found in the data matrix.")

        self.pca_X = pca.fit_transform(pca_data_cleared)  # data in subroom with reduced dimension
        logger.info(f'PCA finished with {pca.get_params()}')
        self.pca_X = np.ascontiguousarray(self.pca_X)
        self.PCs = pca.components_
        # remove negative values from the PCA data by adding the inverse of the minimum to each column
        for i, _ in enumerate(self.pca_X[0, :]):
            pca_min = np.min(self.pca_X[:, i])
            if pca_min < 0:
                self.pca_X[:, i] = np.subtract(self.pca_X[:, i], pca_min)
        self.pca_X = self.pca_X * self.normalization_constant(self.pca_X)
        # TODO save all PCA components to update the result view whenever a change of _n_components is traced
        self.pca_2DX = self.reshape_2d_3d_mv_data(self.pca_X)[0:self._n_components, ...]
        logger.info(f"PCA: reshaped data has shape {self.pca_2DX.shape}")
        self.pca_ready = True

    def randomNNMF(self) -> None:
        logger.info(f'{self.data_2d.shape =}')
        self.fixed_W, self.fixed_H, fit_info = self._fit_nmf_backend(self.data_2d, init='random')
        normalization_factor = self.normalization_constant(self.fixed_W, dtype=d_type)
        # If w is scaled by a, the matrix H is scaled by the inverse value, i.e. X = aW(1/a)H = WH
        self.fixed_W, self.fixed_H = self.fixed_W * normalization_factor, self.fixed_H * normalization_factor
        self.fixed_W_2D = self.reshape_2d_3d_mv_data(self.fixed_W)

        logger.info("Random NNMF outcome:")
        logger.info("Backend: %s", fit_info.get("backend"))
        logger.info("#Iter: %s", fit_info.get("n_iter"))
        if fit_info.get("backend") == "sklearn":
            logger.info("Parameter: \n %s", fit_info.get("params"))
        else:
            logger.info("Torch info: %s", fit_info)

    def reset_seeds(self):
        self.seed_H = np.zeros((self._n_components, self.raw_data_3d.shape[0]))
        self.seed_H_background_flag = np.zeros(self._n_components, dtype=bool)
        self.seed_W = np.zeros((self.data_2d.shape[0], self._n_components))
        self._clear_nnls_abundance_cache()

    def set_H_seed(self, component: int, spectrum: np.array, flag_background:bool=False) -> None:
        if self.seed_H is None:
            # instantiate placeholder
            self.seed_H = np.zeros((self._n_components, self.raw_data_3d.shape[0]))
            self.seed_H_background_flag = np.zeros(self._n_components, dtype=bool)
        if spectrum.shape[0] == self.raw_data_3d.shape[0]:
            self.seed_H[component] = spectrum
            self.seed_H_background_flag[component] = flag_background
        else:
            raise ShapeError(self.raw_data_3d.shape[0], spectrum.shape)

        self._W_prepared = False
        self._clear_nnls_abundance_cache()


    def set_W_seed_mode(self, mode: str):
        aliases = {
            'H weights': 'h_weighted',
            'H-weighted average': 'h_weighted',
            'None': 'average',
            'Average image': 'average',
            'Empty': 'empty',
            'Homogeneous (empty)': 'empty',
            'Selective score map': 'selective_score',
            'NNLS abundance map': 'nnls',
            'NNLS abundance map (recommended)': 'nnls',
        }
        canonical_mode = aliases.get(mode, mode)
        self.w_seed_mode = canonical_mode
        self.full_W_seed = canonical_mode == 'empty'
        self.avg_W_seed = canonical_mode == 'average'
        self.H_weighted_W_seed = canonical_mode == 'h_weighted'
        self._W_prepared = False
        logger.info(
            'W seed mode updated: %s (canonical=%s, avg=%s, h_weighted=%s, empty=%s)',
            mode,
            canonical_mode,
            self.avg_W_seed,
            self.H_weighted_W_seed,
            self.full_W_seed,
        )

    def set_W_seed_matrix(self, W: np.ndarray):
        # check if W has the correct shape
        self._W_prepared = False
        if W.shape[1] != self._n_components:
            raise ShapeError(self._n_components, W.shape[1])
        if W.shape[0] != self.data_2d.shape[0]:
            raise ShapeError(self.data_2d.shape[0], W.shape[0])
        self.seed_W = W
        # check for zeros in the seed matrix, if so the matrix is not prepared
        self._W_prepared =  np.all(self.seed_W)
        logger.info(f'Set W seed matrix, prepared={self._W_prepared}')

    def create_background_component_from_reference(
            self,
            ref_2d: np.ndarray,
            background_component: int,
            radius_px: int,
            smooth_sigma: float = 10.0,
            downsample: int = 1,
            eps: float = 1e-6,
            write_into_seeds: bool = True
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Create a *new* background component from a reference image

        W_bg = rolling_ball(W_signal_image)
        H_bg = weighted mean spectrum (raw data) with weights=W_bg

        Returns
        -------
        W_bg : (n_pixels,) float32
        H_bg : (n_bands,) float32
        """

        # optional downsample for speed
        ds = max(int(downsample), 1)
        ny, nx = ref_2d.shape
        if ds > 1:
            ref_ds = ref_2d[::ds, ::ds]
            rad_ds = max(int(radius_px // ds), 1)
            bg_ds = rolling_ball(ref_ds, radius=rad_ds).astype(np.float32)
            bg = np.repeat(np.repeat(bg_ds, ds, axis=0), ds, axis=1)[:ny, :nx]
        else:
            bg = rolling_ball(ref_2d, radius=int(radius_px)).astype(np.float32)

        W_bg = np.maximum(bg.reshape(-1), eps).astype(np.float32)

        # smoothen the W_bg spatially
        W_bg_3d = W_bg.reshape(self.raw_data_3d.shape[1], self.raw_data_3d.shape[2])
        W_bg_3d = gaussian_filter(W_bg_3d, sigma=smooth_sigma).astype(np.float32)
        W_bg = W_bg_3d.reshape(-1)

        # --- background spectrum from RAW data (more stable than subtracted) ---
        H_bg = np.average(self.data_2d.astype(np.float32), axis=0, weights=W_bg)
        if smooth_sigma and smooth_sigma > 0:
            H_bg = gaussian_filter1d(H_bg, smooth_sigma).astype(np.float32)

        # add small epsilon to avoid zeros
        H_bg = np.maximum(H_bg, eps).astype(np.float32)

        if write_into_seeds:
            # write into seeds (+ mark background)
            if self.seed_H is None or self.seed_W is None:
                self.reset_seeds()

            self.seed_W[:, background_component] = W_bg
            self.set_H_seed(background_component, H_bg, flag_background=True)

        return W_bg, H_bg

    def set_up_random_H_seed(self, i):
        # TODO: check how to set up the best random seed for the H matrix
        if self.seed_H is None:
            self.seed_H = np.zeros((self._n_components, self.raw_data_3d.shape[0]))
        avg_intensity = np.mean(self.data_2d, axis=None)
        self.seed_H[i] = np.full_like(self.seed_H[i], avg_intensity)
        self.seed_H[i] += np.abs(np.random.normal(0, 0.5 * np.amax(self.data_2d), self.seed_H[i].shape))
        self.seed_H[i] = gaussian_filter1d(self.seed_H[i], 10)
        logger.info(f'added jitter to average component {i}')
        # rescale the curve such that its average equals the average of the data
        self.seed_H[i] = self.seed_H[i] * avg_intensity / np.mean(self.seed_H[i], axis=None)
        self._clear_nnls_abundance_cache()


    def set_up_missing_W_seeds(self, skip_spectral_info=False, fill_H_seed: bool = True) -> bool:
        # First step: process all spectral info to create the W seeds
        if not skip_spectral_info:
            self.make_W_seeds_from_spectral_info()
        # first try to initialize from H seeds....
        if not self._W_prepared:
            logger.warning('W seeds not prepared. Trying to set up from H')
            self.estimate_W_seed_matrix_from_H(overwrite=False)
        if not self._W_prepared:
            logger.warning('W seeds still not prepared, using average intensity for remaining components')
            self.set_up_random_W_seed(overwrite=False)
        return self._W_prepared
        # W seed estimation should be done by now, time for H

    def set_up_missing_H_seeds(self) -> bool:
        # 1) use ROIs, this has been done by the analysis manager or by the user manually
        # 2) find seed pixels from spectral info

        # step 1 and 2 have to be done by the analysis manager or the user manually, i.e. the H seeds are filled manually

        # 3) if no seed pixels are found, use the average intensity of the data
        # check if H already exists and which components still must be filled
        if self.seed_H is None:
            self.seed_H = np.zeros((self._n_components, self.data_2d.shape[1]))

        remaining_components = np.array(
            [idx for idx in range(self.seed_H.shape[0]) if not self._has_seed_signal(self.seed_H[idx])]
        )
        logger.info('H components without a usable seed: %s', remaining_components)

        # iterate over all components and create the H seeds
        for cmp in remaining_components:
            logger.info(f'Creating H seed for component {cmp}')
            if self.seed_H_background_flag[cmp]:
                logger.info(f'Component {cmp} is marked as background, using raw data for H seed estimation')
                self.seed_H[cmp] = np.mean(self.data_2d, axis=1)
                self._clear_nnls_abundance_cache()
                return True
            self.set_up_random_H_seed(cmp)
        return True

    def make_W_seeds_from_spectral_info(self, reset_old_seed=True, debug_mode=True):
        """ testing function if the spectal info is correctly interpreted """
        shape_W = (self.data_2d.shape[0], self._n_components)
        if reset_old_seed or self.seed_W is None:
            self.seed_W = np.zeros(shape_W)

        # shape check
        if self.seed_W.shape != shape_W:
            logger.error(f'Invalid shape for W seed matrix: {self.seed_W.shape} != {shape_W}')
            self.seed_W = np.zeros(shape_W)

        # iterate over all components and create the W seeds
        for i in range(self._n_components):
            # find all entries in the self.spectral_info that belong to the current component
            info_list = self.get_sepctral_info_component(i)
            if not info_list:
                logger.info('No spectral info available for component %s in legacy W seed estimation.', i)
                continue
            if len(info_list) > 1:
                logger.warning(f'Multiple spectral info entries found for component {i}, using the first one')
            info = info_list[0]
            logger.info(f'Estimating seed for component {i} with spectral info {info}')
            frames = self.return_resonance_indices(info)
            weights = np.ones(frames.size)
            if self.H_weighted_W_seed:
                if self.seed_H is not None:
                    if self._has_seed_signal(self.seed_H[i]):
                        logger.info(f'Using H weights for W seed estimation for component {i}')
                        weights = self.seed_H[i][frames]

            data = self.resonance_data_2d
            # check if data is background
            if self.seed_H_background_flag[i]:
                logger.info(f'Component {i} is marked as background, using raw data for W seed estimation')
                data = self.data_2d

            res_frames = data[..., frames]
            seed = np.average(res_frames, axis=1, weights=weights)
            self.seed_W[:, i] = seed

        if np.all(self.seed_W):
            self._W_prepared = True

        if debug_mode:
            seed_W_2d = self.seed_W.reshape(self.raw_data_3d.shape[1], self.raw_data_3d.shape[2], -1)
            self.seed_W_view = ImageViewYX()
            self.seed_W_view.setImage(seed_W_2d)
            self.seed_W_view.show()

    def get_sepctral_info_component(self, component: int) -> list[dict[str, float | int]]:
        if self.spectral_info is None:
            logger.warning('No spectral info available')
            return []
        return [info for info in self.spectral_info if info and info.get('Component') == component]

    def return_resonance_indices(self, spectral_info: dict) -> np.ndarray:
        """
        Return the indices of the spectral slices that belong to the defined resonance.
        If the resonance is out of bounds, an array containing the nearest valid index is returned.
        """
        wavenumber = spectral_info['Wavenumber']
        width = spectral_info['Width']

        # Sort wavenumbers but keep track of original indices
        sorted_indices = np.argsort(self.wavenumbers)
        sorted_wavenumbers = self.wavenumbers[sorted_indices]

        # Find the valid range in the sorted wavenumbers
        w_min_sorted = np.searchsorted(sorted_wavenumbers, wavenumber - width, side='left')
        w_max_sorted = np.searchsorted(sorted_wavenumbers, wavenumber + width, side='right') - 1

        logger.debug('Initial sorted resonance bounds for %.3f ± %.3f: [%s, %s]',
                     wavenumber, width, w_min_sorted, w_max_sorted)
        # Ensure valid index bounds
        w_max_sorted = min(w_max_sorted, len(sorted_wavenumbers) - 1)
        w_min_sorted = max(w_min_sorted, 0)

        if w_max_sorted < w_min_sorted:
            # take nearest index
            nearest_idx = (np.abs(sorted_wavenumbers - wavenumber)).argmin()
            w_min_sorted = nearest_idx
            w_max_sorted = nearest_idx
            logger.warning(f'Resonance {wavenumber} ± {width} out of bounds, using nearest index {nearest_idx}, i.e. wavenumber {sorted_wavenumbers[nearest_idx]}')

        # Convert back to original indices
        selected_indices_sorted = np.arange(w_min_sorted, w_max_sorted + 1)
        resonance_indices = sorted_indices[selected_indices_sorted]  # Map back to original order

        logger.info(f"Resonance wavenumbers for {wavenumber} ± {width}: {sorted_wavenumbers[selected_indices_sorted]}")
        # logger.info(f'Selecting indices {resonance_indices}, Info: {spectral_info}')
        return np.sort(resonance_indices)  # Return indices in ascending order of original wavenumbers

    def estimate_W_seed_matrix_from_H(self, spectral_info=None, overwrite=False, skip_components=None):
        """
        Estimate the W seed matrix from the H seed matrix.
        If overwrite is False, only components that are not yet fully set up
        (i.e. contain at least one zero) are estimated.
        """
        eps = getattr(self, "nnmf_epsilon", 1e-8)
        if self.seed_H is None:
            # shape: (n_components, n_bands)
            self.seed_H = np.zeros((self._n_components, self.raw_data_3d.shape[0]))

        if self.seed_W is None:
            # shape: (n_pixels, n_components)
            self.seed_W = np.zeros((self.data_2d.shape[0], self._n_components))

        # which components need seeding / reseeding?
        if overwrite:
            seed_indices = np.arange(self._n_components)
        else:
            # columns that are NOT fully non-zero -> at least one zero element
            seed_indices = np.where(~np.all(self.seed_W, axis=0))[0]

        skip_components = set(skip_components or [])
        if skip_components:
            seed_indices = np.array([i for i in seed_indices if i not in skip_components], dtype=int)

        logger.info('W components to (re)seed from H using %s: %s', self.w_seed_mode, seed_indices)

        for i in seed_indices:
            H = self.seed_H[i]

            # --- case 1: H is completely zero -> use fallback init for both H and W ---
            if not self._has_seed_signal(H, eps=eps):
                logger.info(f'Component H{i} is not set up fully. Skipping model')
                # self._init_unseeded_component(i, bgd=self.seed_H_background_flag[i])
                continue


            logger.info(f'Estimating W seeds from H for component {i}')
            W_col = self.estimate_W_seed_with_H(
                i,
                H,
                spectral_info=spectral_info,
                bgd=self.seed_H_background_flag[i]
            )

            self.seed_W[:, i] = W_col

        # global check: all entries of W must be non-zero to be "prepared"
        if np.all(self.seed_W):
            logger.info('All entries of W are non-zero -> W is prepared.')
            self._W_prepared = True
        else:
            logger.warning('Some W entries are still zero; NNMF precondition not yet fulfilled.')

    def _init_unseeded_component(self, comp_idx: int, bgd: bool = False, dtype=np.uint16):
        """
        Fallback initialization for components that have no H seed at all.
        Creates:
          - a smooth random H (all entries >= eps)
          - a W based on averaged image intensities (all entries >= eps)
        """
        eps = getattr(self, "nnmf_epsilon", 1e-8)
        logger.warning(f'Component {comp_idx} has no H seed; initializing with smooth random H and averaged W.')

        # ---- H: smooth random spectrum ----
        n_bands = self.raw_data_3d.shape[0]
        h = np.random.rand(n_bands)

        # simple box smoothing (no extra deps)
        kernel = np.ones(5, dtype=float) / 5.0
        h = np.convolve(h, kernel, mode="same")

        # make strictly positive and normalize to mean image intensity scale
        mean_intensity = np.mean(self.data_2d, axis=None)
        h = np.maximum(h, eps)
        h /= h.max() * mean_intensity

        self.seed_H[comp_idx, :] = h

        # ---- W: average image over spectral axis ----
        if bgd:
            image_data = self.data_2d
        else:
            image_data = self.resonance_data_2d

        W_col = np.mean(image_data, axis=1)
        W_col = np.maximum(W_col, eps)  # ensure strictly positive
        self.seed_W[:, comp_idx] = W_col

    def estimate_W_seed_with_H(self, component_index: int,
                               H: np.ndarray,
                               spectral_info: np.ndarray | None = None,
                               bgd: bool = False) -> np.ndarray:
        """
        Estimate a *strictly positive* W seed for one component given its H seed.

        The active method is controlled by ``self.w_seed_mode``:
        - ``nnls``: non-negative least-squares abundance map from all available H seeds
        - ``selective_score``: target projection weighted by its selectivity against competing H seeds
        - ``h_weighted``: legacy exponential H-weighted average
        - ``average``: average image
        - ``empty``: homogeneous seed
        """
        eps = getattr(self, "nnmf_epsilon", 1e-8)

        if spectral_info is not None:
            # can be used later; not used yet
            logger.debug('spectral_info is currently not used inside estimate_W_seed_with_H.')

        prepared_target = self._prepare_seed_spectrum(H, eps=eps)
        if prepared_target is None:
            logger.warning('Component %s has no usable H seed shape. Falling back to averaged image.', component_index)
            W_image = np.mean(self.data_2d, axis=1)
            return np.maximum(W_image, eps)

        image_data, source_key = self._get_image_data_and_source_key(component_index, bgd=bgd)

        n_pixels, n_bands = image_data.shape

        # ------------------------------------------------------------------
        # 1) NEW SELECTIVE MODES
        # ------------------------------------------------------------------
        if self.w_seed_mode == 'nnls':
            return self._estimate_nnls_abundance_map(image_data, component_index, prepared_target, eps, source_key)

        if self.w_seed_mode == 'selective_score':
            return self._estimate_selective_score_map(image_data, component_index, prepared_target, eps)

        # ------------------------------------------------------------------
        # 2) LEGACY MODES
        # ------------------------------------------------------------------
        if self.H_weighted_W_seed:
            logger.info('Using exponential H weights for W seed estimation.')
            # make exponential weights
            if self._has_seed_signal(H, eps=eps):
                weights = H - np.min(H)
                weights = np.maximum(weights, 0.0)
                max_weight = np.max(weights)
                if max_weight <= eps:
                    return np.maximum(np.mean(image_data, axis=1), eps)
                weights /= max_weight
                weights = np.exp(weights) - 1.0  # exponential scaling
                logger.debug('Using exponential H weights for W seed estimation with shape %s.', weights.shape)
                return np.maximum(np.average(image_data, axis=1, weights=weights), eps)

        if self.avg_W_seed:
            logger.info('avg_W_seed=True: filling W with averaged image (clamped to eps).')
            W_image = np.mean(image_data, axis=1)
            W_image = np.maximum(W_image, eps)
            return W_image

        if self.full_W_seed:
            logger.info('full_W_seed=True: using full W seed mode (constant, >= eps).')
            avg_int = np.mean(image_data, axis=None)
            W_image = np.full(n_pixels, max(float(avg_int), eps), dtype=np.float64)
            return W_image

        # ------------------------------------------------------------------
        # 3) Fallback: maximum-intensity slice at peak of H (clamped to eps)
        # ------------------------------------------------------------------
        logger.warning('No W seed mode selected, using maximum-intensity slice at H peak (clamped to eps).')
        peak_idx = int(np.argmax(H))
        W_image = self.data_2d[:, peak_idx]
        W_image = np.maximum(W_image, eps)
        return W_image

    @staticmethod
    def normalization_constant(img, dtype = '16bit') -> float:
        dtypes = {'16bit': 65535, '8bit': 255}
        try:
            max_val = dtypes[dtype]
        except KeyError as e:
            e('Unknown datatype')
        cur_max = np.nanmax(img, axis=None)
        return max_val / cur_max

    def set_up_random_W_seed(self, overwrite=True):
        """
        Set up random W seed matrix for all components that are not yet set up.

        Parameters
        ----------
        overwrite : bool
            If True, all components are overwritten. If False, only components that are not yet set up are filled.

        Returns
        -------

        """
        logger.info('Setting up random W seed')
        if self.seed_W is None:
            self.seed_W = np.zeros((self.data_2d.shape[0], self._n_components))

        eps = getattr(self, "nnmf_epsilon", 1e-8)
        if self.full_W_seed:
            avg_int = max(float(np.mean(self.data_2d, axis=None)), eps)
            fill_data = np.full(self.data_2d.shape[0], avg_int, dtype=np.float64)
        else:
            fill_data = np.maximum(np.mean(self.data_2d, axis=1), eps)

        if overwrite:
            frames = np.arange(self._n_components)
        else:
            # find components that are not yet set up
            frames = np.where(~np.all(self.seed_W, axis=0))[0]

        for frame in frames:
            self.seed_W[:, frame] = fill_data

        self._W_prepared = True



    def reshape_2d_3d_mv_data(self, data: np.ndarray) -> np.ndarray:
        z, y, x = self.raw_data_3d.shape
        # Revert order back and move spectral axis back to first dimension (tiff file convention)!
        return np.moveaxis(data.reshape(y, x, -1), -1, 0)

    def NNMF(self, skip_seed_fining=False) -> bool:
        """
        Function that executes the NNMF with the seeds provided by the user.
        Seeds must be set before calling this function.
        Returns:
        """
        # this function expects the W seed already be set up, for instance from spectral info inside the analysis
        # manager.
        # W seeds that are not fully prepared are calculated from H seeds
        if not skip_seed_fining:
            """ Really basic seed estimation. Only takes H into account and makes W from H"""
            # H must be set outside of the analyzer manually
            # check if all components have a seed, the check of H is included in the seed estimation
            if not self._W_prepared:
                # TODO more sophisticated seed estimation
                self.estimate_W_seed_matrix_from_H()
                # here also the seed for H is checked in the same step and filled if necessary
            if self.seed_W is None or not np.all(self.seed_W):
                logger.error('NNMF aborted: No seed W matrix available or not completely filled')
                return False
        else:
            logger.warning('Skipping seed estimation for NNMF; seeds are assumed to be set')
            if not self.seed_W.all() and self.seed_H.all():
                logger.error('NNMF aborted: No seed W matrix available or not completely filled')
                return False

        logger.info(f'{datetime.now()}: Starting NNMF with custom seeds')

        logger.info(f'{self.data_2d.shape =}')
        # copy the seeds because otherwise the model will overwrite the seed values

        # check the dtype of the data and seeds to be all float32

        self.fixed_W, self.fixed_H, fit_info = self._fit_nmf_backend(
            self.data_2d,
            init='custom',
            w_init=self.seed_W.astype(np.float32),
            h_init=self.seed_H.astype(np.float32),
        )
        normalization_factor = self.normalization_constant(self.fixed_W, dtype=d_type)
        # If w is scaled by a, the matrix H is scaled by the inverse value, i.e. X = aW(1/a)H = WH
        self.fixed_W, self.fixed_H = self.fixed_W * normalization_factor, self.fixed_H
        self.fixed_W_2D = self.reshape_2d_3d_mv_data(self.fixed_W)

        logger.info("Custom NNMF outcome: backend=%s, #Iter=%s", fit_info.get("backend"), fit_info.get("n_iter"))
        if fit_info.get("backend") == "sklearn":
            logger.info("Parameter: \n %s", fit_info.get("params"))
        else:
            logger.info("Torch info: %s", fit_info)
        return True

    def reset_results(self):
        self.fixed_H = None
        self.fixed_W = None
        # 2D equivalent with spectral slices at axis 0
        self.fixed_W_2D = None
        self.seed_pixels = None
        self.data_2d = None # non-standardized data, order spatial info axis 0, wavenumbers axis 1
        self.pca_data_std = None    # standardized data for PCA
        self.pca_X = None
        self.pca_2DX = None
        self.PCs = None
        self.pca_ready = False
        self.seed_H = None
        self.seed_W = None
        self._W_prepared = False

    # Optional matplotlib inspection helpers
    def plot_PCA_mpl(self):
        # Convenience helper for offline inspection of PCA components.
        for i in range(0, self._n_components):  # only plot the interesting components
            l, = plt.plot(self.PCs[i, :], label=f"PC {i:.0f}")
            # self.ax1_lines.append(l)
        ax = plt.gca()
        ax.legend()
        ax.set_xlabel('Raman shift [cm$^{-1}$]')
        ax.set_ylabel('Intensity [a. u.]')
        ax.set_title('PCs')
        # plt.gcf().subplots_adjust(**adjust_options_tight)

        nx = int(np.sqrt(self._n_components))
        ny = self._n_components - nx
        fig, ax = plt.subplots(nx, ny)
        cur_cmp = 0
        for i in range(nx):
            for j in range(ny):
                ax[i, j].imshow(self.pca_2DX[cur_cmp, ...], cmap='viridis')
                cur_cmp += 1
        plt.show()

    def plot_nnmf_mpl(self):
        # Convenience helper for offline inspection of NNMF results.
        # loadings
        for i in range(0, self._n_components):  # only plot the interesting components
            l, = plt.plot(self.fixed_H[i, :], label=fr" H {i:.0f}")
            # self.ax1_lines.append(l)
        ax = plt.gca()
        ax.legend()
        ax.set_xlabel('Raman shift [cm$^{-1}$]')
        ax.set_ylabel('Intensity [a. u.]')
        ax.set_title(r'$H$')

        nx = int(np.sqrt(self._n_components))
        ny = self._n_components - nx
        fig, ax = plt.subplots(nx, ny)
        cur_cmp = 0
        for i in range(nx):
            for j in range(ny):
                # reshape W to 2D typical (FIJI) image shape and move spectral axis back to position 0
                ax[i, j].imshow(self.fixed_W_2D[cur_cmp, ...], cmap='viridis')
                cur_cmp += 1
        plt.show()


class ShapeError(Exception):
    def __init__(self, expected_shape, actual_shape):
        self.expected_shape = expected_shape
        self.actual_shape = actual_shape
        message = f"Expected shape {expected_shape}, but got shape {actual_shape}."
        super().__init__(message)

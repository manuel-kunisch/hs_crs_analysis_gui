import logging
from datetime import datetime

import numpy as np
from matplotlib import pyplot as plt
from scipy.ndimage import gaussian_filter1d, gaussian_filter
from skimage.restoration import rolling_ball
from sklearn.decomposition import PCA, NMF

from contents.custom_pyqt_objects import ImageViewYX

d_type = '16bit'

logger = logging.getLogger(__name__)

class MultivariateAnalyzer(object):
    def __init__(self, data, n_components, wavenumbers, method='NNMF'):
        self.resonance_data_zyx = None
        self.full_W_seed = False
        self.H_weighted_W_seed = False
        self.avg_W_seed = True
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
        self.update_image_data(data, n_components, wavenumbers)

    def update_spectral_info(self, spectral_info: list[dict[str, float | int]]):
        self.spectral_info = spectral_info
        logger.info(f'MV Anaylzer: Updated spectral info: {self.spectral_info}')
        self._W_prepared = False

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
        self.avg_W_seed = True
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
        nnmf_model = NMF(n_components=self._n_components, init='random', random_state=0, max_iter=1000, solver='mu')
        logger.info(f'{self.data_2d.shape =}')
        self.fixed_W = nnmf_model.fit_transform(self.data_2d)
        self.fixed_H = nnmf_model.components_
        normalization_factor = self.normalization_constant(self.fixed_W, dtype=d_type)
        # If w is scaled by a, the matrix H is scaled by the inverse value, i.e. X = aW(1/a)H = WH
        self.fixed_W, self.fixed_H = self.fixed_W * normalization_factor, self.fixed_H * normalization_factor
        self.fixed_W_2D = self.reshape_2d_3d_mv_data(self.fixed_W)

        logger.info("Random NNMF outcome:")
        logger.info("#Iter: {}".format(nnmf_model.n_iter_))
        logger.info("Parameter: \n {}".format(nnmf_model.get_params))

    def reset_seeds(self):
        self.seed_H = np.zeros((self._n_components, self.raw_data_3d.shape[0]))
        self.seed_H_background_flag = np.zeros(self._n_components, dtype=bool)
        self.seed_W = np.zeros((self.data_2d.shape[0], self._n_components))

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


    def set_W_seed_mode(self, mode: str):
        if mode == 'H weights':
            self.full_W_seed = False
            self.avg_W_seed = False
            self.H_weighted_W_seed = True
        elif mode == 'None':
            self.full_W_seed = False
            self.avg_W_seed = True
            # self.H_weighted_W_seed = False
        elif mode == 'Empty':
            self.full_W_seed = True
            self.avg_W_seed = False
            # self.H_weighted_W_seed = False
        self._W_prepared = False
        logger.info(f"W Seed Mode Updated: {mode}, _skip_W_seed={self.avg_W_seed}, H_weighted_W_seed={self.H_weighted_W_seed}, "
                    f"_full_W_seed={self.full_W_seed}")

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

        remaining_components = np.where(~np.all(self.seed_H, axis=1))[0]
        logger.info(f'H Components without seed or zeros in component: {remaining_components}')

        # iterate over all components and create the H seeds
        for cmp in remaining_components:
            logger.info(f'Creating H seed for component {cmp}')
            if self.seed_H_background_flag[cmp]:
                logger.info(f'Component {cmp} is marked as background, using raw data for H seed estimation')
                self.seed_H[cmp] = np.mean(self.data_2d, axis=1)
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
            if len(info_list) > 1:
                logger.warning(f'Multiple spectral info entries found for component {i}, using the first one')
            info = info_list[0]
            logger.info(f'Estimating seed for component {i} with spectral info {info}')
            frames = self.return_resonance_indices(info)
            weights = np.ones(frames.size)
            if self.H_weighted_W_seed:
                if self.seed_H is not None:
                    if np.all(self.seed_H[i]):
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
        return [info for info in self.spectral_info if info['Component'] == component]

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

        # Ensure valid index bounds
        w_max_sorted = min(w_max_sorted, len(sorted_wavenumbers) - 1)
        w_min_sorted = max(w_min_sorted, 0)

        if w_max_sorted < w_min_sorted:
            if wavenumber - width < sorted_wavenumbers[0]:
                w_min_sorted = 0
                w_max_sorted = 0
            if wavenumber + width > sorted_wavenumbers[-1]:
                w_max_sorted = sorted_wavenumbers.size - 1
                w_min_sorted = sorted_wavenumbers.size - 1
            logger.warning(
                f"Invalid range (w_min={w_min_sorted}, w_max={w_max_sorted}). Skipping.")

        # Convert back to original indices
        selected_indices_sorted = np.arange(w_min_sorted, w_max_sorted + 1)
        resonance_indices = sorted_indices[selected_indices_sorted]  # Map back to original order

        # logger.info(f'Selecting indices {resonance_indices}, Info: {spectral_info}')
        return np.sort(resonance_indices)  # Return indices in ascending order of original wavenumbers

    def estimate_W_seed_matrix_from_H(self, spectral_info=None, overwrite=False):
        """
        Estimate the W seed matrix from the H seed matrix.
        If overwrite is False, only components that are not yet fully set up
        (i.e. contain at least one zero) are estimated.
        """
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

        logger.info(f'W components to (re)seed (need non-zero entries): {seed_indices}')

        for i in seed_indices:
            H = self.seed_H[i]

            # --- case 1: H is completely zero -> use fallback init for both H and W ---
            if not np.all(H):
                logger.info(f'Component H{i} is not set up fully. Skipping model')
                # self._init_unseeded_component(i, bgd=self.seed_H_background_flag[i])
                continue


            logger.info(f'Estimating W seeds from H for component {i}')
            W_col = self.estimate_W_seed_with_H(
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

    def estimate_W_seed_with_H(self, H: np.ndarray,
                               spectral_info: np.ndarray | None = None,
                               bgd: bool = False) -> np.ndarray:
        """
        Estimate a *strictly positive* W seed for one component given its H seed.

        - For non-background components (bgd=False), we use resonance_data_2d.
        - For background, we use data_2d.
        - If self.H_weighted_W_seed is True:
            * project spectra onto H
            * normalize scores to [0, 1]
            * optionally log-compress
            * build a mask via percentile
            * inside mask: high scores
            * outside mask: small epsilon (NOT zero)
        """
        eps = getattr(self, "nnmf_epsilon", 1e-8)

        if spectral_info is not None:
            # can be used later; not used yet
            logger.debug('spectral_info is currently not used inside estimate_W_seed_with_H.')

        # --- choose data source (n_pixels x n_bands) ---
        if bgd:
            image_data = self.data_2d
            logger.info('Background component! Using raw data for W seed estimation.')
        else:
            image_data = self.resonance_data_2d
            logger.info('Using subtracted data for W seed estimation from H.')

        n_pixels, n_bands = image_data.shape

        # ------------------------------------------------------------------
        # 1) MAIN MODE: exponential weights
        # ------------------------------------------------------------------
        if self.H_weighted_W_seed:
            logger.info('Using exponential H weights for W seed estimation.')
            # make exponential weights
            if np.any(H):
                weights = H - np.min(H)
                weights /= np.max(weights)
                weights = np.exp(weights) - 1.0  # exponential scaling
                print(f"weights {weights}")
                return np.average(image_data, axis=1, weights=weights)

        # ------------------------------------------------------------------
        # 2) OTHER MODES
        # ------------------------------------------------------------------
        if self.avg_W_seed:
            logger.info('avg_W_seed=True: filling W with averaged image (clamped to eps).')
            W_image = np.mean(image_data, axis=1)
            W_image = np.maximum(W_image, eps)
            return W_image

        if self.full_W_seed:
            logger.info('full_W_seed=True: using full W seed mode (constant, >= eps).')
            avg_int = np.mean(image_data, axis=None)
            W_image = np.full_like(image_data[:, 0], max(avg_int, eps), dtype=image_data.dtype)
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

        if self.avg_W_seed:
            # fill with avg intensity
            fill_data = np.mean(self.data_2d, axis=1)
        elif self.full_W_seed:
            # fill with full data
            fill_data = np.mean(self.data_2d, axis=1)
        else:
            # fill with random data
            fill_data = np.random.normal(1, 0.5 * np.amax(self.data_2d), self.seed_W[:, 0].shape)

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

        nnmf_model = NMF(n_components=self._n_components, init='custom', random_state=0, max_iter=1000, solver='mu')
        logger.info(f'{self.data_2d.shape =}')
        # copy the seeds because otherwise the model will overwrite the seed values

        # check the dtype of the data and seeds to be all float32

        self.fixed_W = nnmf_model.fit_transform(self.data_2d, H=self.seed_H.astype(np.float32), W=self.seed_W.astype(np.float32))
        self.fixed_H = nnmf_model.components_
        normalization_factor = self.normalization_constant(self.fixed_W, dtype=d_type)
        # If w is scaled by a, the matrix H is scaled by the inverse value, i.e. X = aW(1/a)H = WH
        self.fixed_W, self.fixed_H = self.fixed_W * normalization_factor, self.fixed_H
        self.fixed_W_2D = self.reshape_2d_3d_mv_data(self.fixed_W)

        logger.info("Custom NNMF outcome: #Iter: {}".format(nnmf_model.n_iter_))
        logger.info("Parameter: \n {}".format(nnmf_model.get_params))
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

    # %% debug functions
    def plot_PCA_mpl(self):
        # FIXME: debug method, remove later
        # TODO: add possibility to add a QT Canvas where data is plotted in init
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
        # FIXME debug method, remove later
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
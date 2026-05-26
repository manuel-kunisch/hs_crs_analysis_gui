import logging
import os

import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class SpectrumLoader:
    def __init__(self, target_wavenumbers, dtype=np.uint16):
        self.target_wavenumbers: np.ndarray or None = target_wavenumbers
        self.wavenumbers: np.ndarray or None = None

        # Changed to lists to hold multiple components
        self.spectra: list[np.ndarray] = []
        self.target_spectra: list[np.ndarray] = []
        self.names: list[str] = []

        self.dtype: np.dtype = dtype

    def update_wavenumbers(self, target_wavenumbers):
        self.target_wavenumbers = target_wavenumbers

    def load_spectrum(self, path):
        # Clear previous data
        self.spectra = []
        self.names = []

        if path.endswith('.txt'):
            self.wavenumbers, self.spectra, self.names = self._load_txt_spectrum(path)
        elif path.endswith('.asc'):
            self.wavenumbers, self.spectra, self.names = self._load_asc_spectrum(path)
        elif path.endswith('.csv'):
            self.wavenumbers, self.spectra, self.names = self._load_csv_spectrum(path)

        self.target_spectra = self.prepare_spectrum()
        return self.target_spectra

    def _load_two_column_text_spectrum(self, path):
        wavenumbers = []
        intensities = []
        skipped_lines = 0

        with open(path, 'r', encoding='utf-8-sig') as f:
            for line_number, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue

                parts = line.split()
                if len(parts) < 2:
                    skipped_lines += 1
                    logger.debug("Skipping short spectrum line %s in %s: %r", line_number, path, raw_line.rstrip())
                    continue

                try:
                    wavenumbers.append(float(parts[0]))
                    intensities.append(float(parts[1]))
                except ValueError:
                    skipped_lines += 1
                    logger.debug("Skipping non-numeric spectrum line %s in %s: %r", line_number, path, raw_line.rstrip())
                    continue

        if not wavenumbers:
            raise ValueError(f"No numeric two-column spectrum data found in {path}.")

        if skipped_lines:
            logger.info("Ignored %s non-numeric/header line(s) while loading %s.", skipped_lines, path)

        name = os.path.splitext(os.path.basename(path))[0]
        # Return as lists to maintain consistency with multi-column CSV
        return np.array(wavenumbers), [np.array(intensities)], [name]

    def _load_txt_spectrum(self, path):
        return self._load_two_column_text_spectrum(path)

    def _load_asc_spectrum(self, path):
        return self._load_two_column_text_spectrum(path)

    def _load_csv_spectrum(self, path):
        # 1. Read header to get names
        with open(path, 'r') as f:
            header_line = f.readline()
            header_parts = [h.strip().replace('"', '') for h in header_line.split(',')]

        # 2. Load data
        # skip_header=1 avoids the text row
        data = np.genfromtxt(path, delimiter=',', skip_header=1)

        wavenumbers = data[:, 0]
        loaded_spectra = []
        loaded_names = []

        # 3. Iterate over all columns starting from index 1 (Intensity columns)
        # data.shape[1] gives total columns (wavenumber + N components)
        for i in range(1, data.shape[1]):
            # Extract intensity column
            loaded_spectra.append(data[:, i])

            # Extract name from header if available, otherwise generic name
            if i < len(header_parts):
                loaded_names.append(header_parts[i])
            else:
                loaded_names.append(f"Component {i}")

        return wavenumbers, loaded_spectra, loaded_names

    def prepare_spectrum(self, scale_to_dtype=False) -> list[np.ndarray]:
        self.interpolate_and_cut_spectrum()

        if scale_to_dtype:
            logger.info("Scaling spectra to dtype: %s", self.dtype)
            self.scale_to_dtype()

        return self.target_spectra

    def scale_to_dtype(self):
        # Scale each target spectrum individually
        scaled_spectra = []
        for spec in self.target_spectra:
            max_value = np.max(spec)
            if max_value > 0:
                scaled = (spec / max_value * np.iinfo(self.dtype).max).astype(self.dtype)
            else:
                scaled = spec.astype(self.dtype)
            scaled_spectra.append(scaled)
        self.target_spectra = scaled_spectra

    def interpolate_and_cut_spectrum(self):
        # 1. Handle Wavenumber Sorting
        if np.amin(np.diff(self.wavenumbers)) < 0:
            logger.info("Wavenumbers are not ordered. Sorting them.")
            sort_idx = np.argsort(self.wavenumbers)
            self.wavenumbers = self.wavenumbers[sort_idx]
            # Sort every loaded spectrum to match the new wavenumber order
            self.spectra = [s[sort_idx] for s in self.spectra]

        # 2. Check Range
        if self.target_wavenumbers[0] < self.wavenumbers[0] or self.target_wavenumbers[-1] > self.wavenumbers[-1]:
            logger.warning("Wavenumbers are out of range. Extrapolating. This may cause artifacts.")

        # 3. Interpolate EVERY loaded spectrum
        self.target_spectra = []
        for spec in self.spectra:
            interp_spec = np.interp(self.target_wavenumbers, self.wavenumbers, spec)
            self.target_spectra.append(interp_spec)

if __name__ == '__main__':
    wavenumbers = np.linspace(2600, 3100, 101)
    loader = SpectrumLoader(wavenumbers)
    # loader.load_spectrum("../example_data/Beads Spektren/09_02_2022/2022_02_09_polystyrene_3um_bads_glass_647nm_790nmcent_600gr_500nm_blz_10x10s_02.asc")
    loader.load_spectrum("../2025_03_17_12-38-30_W_seeds.csv")
    plt.subplot(2, 1, 1)
    plt.title("Original Spectrum")
    plt.plot(loader.wavenumbers, loader.spectrum)
    plt.subplot(2, 1, 2)
    plt.title("Interpolated Spectrum")
    plt.plot(loader.target_wavenumbers, loader.target_spectrum)
    plt.show()

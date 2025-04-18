import logging

import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class SpectrumLoader:
    def __init__(self, target_wavenumbers, dtype=np.uint16):
        self.target_wavenumbers: np.ndarray or None= target_wavenumbers
        self.wavenumbers: np.ndarray or None = None
        self.spectrum: np.ndarray or None = None
        self.target_spectrum: np.ndarray or None= None
        self.name: str or None = None
        self.dtype: np.dtype = dtype

    def update_wavenumbers(self, target_wavenumbers):
        self.target_wavenumbers = target_wavenumbers

    def load_spectrum(self, path):
        if path.endswith('.txt'):
            self.wavenumbers, self.spectrum = self._load_txt_spectrum(path)
        elif path.endswith('.asc'):
            self.wavenumbers, self.spectrum = self._load_asc_spectrum(path)
        elif path.endswith('.csv'):
            self.wavenumbers, self.spectrum = self._load_csv_spectrum(path)
        self.target_spectrum = self.prepare_spectrum()
        return self.target_spectrum

    def _load_txt_spectrum(self, path):
        with open(path, 'r') as f:
            lines = f.readlines()
            wavenumbers = []
            intensities = []
            for line in lines:
                parts = line.split()
                wavenumbers.append(float(parts[0]))
                intensities.append(float(parts[1]))
            self.name = path.split('/')[-1].split('.')[0]
            return np.array(wavenumbers), np.array(intensities)

    def _load_asc_spectrum(self, path):
        with open(path, 'r') as f:
            lines = f.readlines()
            wavenumbers = []
            intensities = []
            for line in lines:
                parts = line.split()
                wavenumbers.append(float(parts[0]))
                intensities.append(float(parts[1]))
            self.name = path.split('/')[-1].split('.')[0]
            return np.array(wavenumbers), np.array(intensities)

    def _load_csv_spectrum(self, path):
        # readin the csv file and extract the header
        with open(path, 'r') as f:
            lines = f.readlines()
            header = lines[0].split(',')
            data = np.genfromtxt(path, delimiter=',', skip_header=1)
        # check if there are multiple seeds in the csv file
        if data.shape[1] > 2:
            logger.info("Multiple seeds found in csv file. Using first seed.")
            """
            # extract the component numbers from the header columns starting with "Component"
            components = []
            component_cols = []
            for col in header:
                if col.startswith('Component'):
                    components.append(int(col.split(' ')[-1]))
                    component_cols.append(col)
            # extract the data for each component
            component_data = []
            for i, component in enumerate(components):
                component_data.append(data[:, i + 1])
            """
        self.name = path.split('/')[-1].split('.')[0]
        return data[:, 0], data[:, 1]

    def prepare_spectrum(self):
        self.interpolate_and_cut_spectrum()
        self.scale_to_dtype()
        return self.target_spectrum

    def scale_to_dtype(self):
        # check max_value of spectrum
        max_value = np.max(self.target_spectrum)
        # scale spectrum to dtype
        self.target_spectrum = (self.target_spectrum / max_value * np.iinfo(self.dtype).max).astype(self.dtype)


    def interpolate_and_cut_spectrum(self) -> np.ndarray:
        # check if the wavenumbers are ordered
        if np.amin(np.diff(self.wavenumbers)) < 0:
            logger.info("Wavenumbers are not ordered. Sorting them.")
            sort_idx = np.argsort(self.wavenumbers)
            print(self.wavenumbers)
            self.wavenumbers = self.wavenumbers[sort_idx]
            self.spectrum = self.spectrum[sort_idx]
            # target wavenumbers do not need to be sorted
        # interpolate the spectrum
        self.target_spectrum = np.interp(self.target_wavenumbers, self.wavenumbers, self.spectrum)
        # TODO: define values outside of the wavenumber range (default is spectrum[0] and spectrum[-1])
        if self.target_wavenumbers[0] < self.wavenumbers[0] or self.target_wavenumbers[-1] > self.wavenumbers[-1]:
            logger.warning("Wavenumbers are out of range. Extrapolating. This may cause artifacts.")
        return self.target_spectrum

    def inter_and_extrapolate_spectrum(self) -> np.ndarray:
        raise DeprecationWarning("This method is deprecated. Use interpolate_and_cut_spectrum instead.")
        # self.target_spectrum = np.interp(self.target_wavenumbers, self.wavenumbers, self.spectrum, left=0, right=0)

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
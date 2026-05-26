# -*- coding: utf-8 -*-
"""
Created on Sun Nov 27 10:44:23 2022

@author: Manuel
"""

import tkinter as tk

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from scipy.optimize import curve_fit

show_fits = False    # Debugging, remove in final version

def seed_pixels(pca_data, wavenumbers, cmps: int, assumed_resonances: list,
                width: list, eps_list: list,
                patch_dict: dict, size, ratio = False, exclude=False,
                px_threshold=10000):
    channels = pca_data.shape[-1]
    relevant_index = []
    H_pixel = []
    seed_H=np.zeros((cmps,channels))
    poss_idx_px = np.arange(0, pca_data.shape[0], dtype='int')
    # converting the selected seed data to a sueful structure
    given_res = {}
    for patch_idx, patch_values in patch_dict['seed'].items():
      cmp_value = patch_values['cmp']
      if cmp_value in given_res:
        given_res[cmp_value].append(patch_idx)
      else:
        given_res[cmp_value] = [patch_idx]
    print(given_res)
        # make a new dictionary containing all different 
    for i,res in enumerate(assumed_resonances):
        print('-'*5, 'Resonance ', i, '-'*5)
        r_res,initial_idx=find_nearest(wavenumbers, res)                  #resonance that is in our range
        value_max,idx_max=find_nearest(wavenumbers, res-width[i]/2)         #initial borders for our guess
        value_min,idx_min=find_nearest(wavenumbers, res+width[i]/2)
        if idx_min > idx_max:
            # Checking the order
            dummy_v, dummy_i = value_min, idx_min
            value_min, idx_min = value_max, idx_max
            value_max, idx_max = dummy_v, dummy_i
        print('Looking for resonances within the range of indices: [%i, %i]'%(idx_min, idx_max))
        if i in given_res:
            seed_indices = []
            seed_data = []
            # dummy for user-selected seeds
            print('Using user selection for resonance %i'%i)
            for patch_idx in given_res[i]:
                cur_patch = patch_dict['seed'][patch_idx]
                coord = cur_patch['coords']
                seed_indices.append(convert_index_range(coord, size))
                seed_data.append(cur_patch['signal'])
            H_pixel.append([[x] for x in sum(seed_indices, [])])
            mean_array = np.mean(seed_data, axis=0)
            print(f'Averaging {len(seed_data)} selection(s).')
            seed_H[i,:] = mean_array
            resonance_slice_idx = np.argmax(seed_H[i,idx_min:idx_max+1]) + idx_min
            relevant_index.append({'idx_min': idx_min , 'idx':resonance_slice_idx,
                                   'idx_max': idx_max, 'max': seed_H[i,resonance_slice_idx]})
            continue
        if exclude:
            print('Excluding previous indices')
            # exclude pixels that have already been used
            """
            make this optional, make it clear for the user that the first resonance should
            be the most distinct...
            """
            try:
                idx_to_clear = H_pixel[-1]
                # avoid looping 
                remove = np.argwhere(np.isin(poss_idx_px, idx_to_clear)).ravel()
                poss_idx_px = np.delete(poss_idx_px, remove)
            except IndexError:
                print('first_loop')
        
        
        for bgd_data in patch_dict['bgd'].values():
            coords = bgd_data['coords']
            # coordinates are always sorted in zoom_and_pan class
            r = convert_index_range(coords, size)
            remove_idx = np.argwhere(np.isin(poss_idx_px, r)).ravel()
            poss_idx_px = np.delete(poss_idx_px, remove_idx)
            print('DELETED')

        """
        this must also be an option for the user
        """
        
        if ratio:
            print('RATIO MODE')
            pca_data_ = pca_data.copy()
            res_range = pca_data_[:,idx_min:idx_max+1]
            # build ratios to 
            if i >= 1:
                mean_ = np.vstack([np.mean(pca_data_[:, relevant_index[i-1]['idx_min']:relevant_index[i-1]['idx_max']], axis=1)]*res_range.shape[-1])
                mean_ = np.swapaxes(mean_,0,-1)
                pca_data_ = np.divide(res_range,mean_)
            else:
                pca_data_ = res_range
            real_resonance=np.argmax(np.amax(pca_data_[poss_idx_px,:],axis=0), axis=0)
        else:
            real_resonance=np.argmax(np.amax(pca_data[poss_idx_px,idx_min:idx_max+1],axis=0), axis=0)
        resonance_slice_idx=real_resonance+idx_min
        cor_slice=pca_data[:,resonance_slice_idx] 
        
        
        print("Reonance "+str(i)+ " found (based on your entry) at slice {}".format(resonance_slice_idx)+", which equals a Raman shift of %.1f 1/cm"%(wavenumbers[resonance_slice_idx]))
        
        print('Setting up H %i:'%(i))
        
        epsilon = float(eps_list[i])  # resonances are sorted, assignment of the correct epsilon  
        # kill pixels that have too much intensity in other slices:        
        slice_max = np.amax(cor_slice)
        # careful map possible indices back to the original structure!
        new_idx = np.argwhere(cor_slice[poss_idx_px]>epsilon*slice_max)
        # print(new_idx)
        # print(poss_idx_px)
        CARS_pixel=poss_idx_px[new_idx]
        if len(CARS_pixel) == 0:
            print('No pixels found, taking maximum of possible pixels instead.')
            CARS_pixel = poss_idx_px[np.argmax(cor_slice[poss_idx_px])]
            
        
        pixel_averaged=np.size(CARS_pixel)
        
        print("Pixel where intensity of the signal is larger than {}% of maximum CARS signal:{} "
              .format(epsilon*100,pixel_averaged))
        
        cmp_number = cmps-1-i
        if pixel_averaged > px_threshold:
            aw = tk.messagebox.askyesno('Crtitical number of seed pixels',
                                        'You are currently dealing with %i seeds ' % pixel_averaged +
                                        'for H%i. ' % cmp_number + '\n Large numbers may increase computation times massively.\n' +
                                        'Would you like to automatically adjust the ε threshold to average %d pixel?' % px_threshold +
                                        '\nPress "No" to proceed.')
            if aw:
                print('Adjusting threshold ε.')
                CARS_pixel = np.concatenate(CARS_pixel)  # Flatten the array
                n_px = tk.simpledialog.askinteger('Number of seed pixels', 
                                                  'Please enter the number of pixels to average.',
                                                  minvalue=0, maxvalue=50000)
                px_sorted = np.argsort(cor_slice[CARS_pixel])[::-1]
                CARS_pixel = CARS_pixel[px_sorted[:n_px]]
                CARS_pixel = np.reshape(CARS_pixel, (-1,1))    # Reformatting
                print(slice_max)
                print()
                print('New ε=%f' %(float(cor_slice[CARS_pixel[-1]]) / slice_max))
        CARS_pixel = CARS_pixel.tolist()
        H_pixel.append(CARS_pixel)
        avg_pixel_data=pca_data[CARS_pixel,:] #indices of pixel with highest resonance
        print("Try to average pixel data of shape: {}".format(np.shape(avg_pixel_data))+
              " as initialization for H {}".format(cmp_number)) 
        seed_H[i,:]=np.mean(avg_pixel_data, axis=0)
        """
        # This only works for clear gaussian peaks, use user input instead
        w_min, w_max = find_slices(seed_H[i,:], .9, imin = idx_min, imax = idx_max+1)
        
        if w_max - w_min >= channels-1:
            w_max = idx_max
            w_min = idx_min
            print('Could not find appropriate slices for W. You initial guess is used instead')
        """
        
        p_guess = [slice_max, wavenumbers[resonance_slice_idx], 2.355*width[i]]     # last param is FWHM
        try:
            popt, pcov = curve_fit(gauss, wavenumbers, seed_H[i,:], p0=p_guess)
            print(popt)
            # THE PARAMATERS CAN (SHOULD) BE USED TO RATE THE QUALITY OF THE SEEDS!
            if show_fits:
                root = tk.Tk()
                fig, ax = plt.subplots(1,1)
                FigureCanvasTkAgg(fig, root).get_tk_widget().pack()
                ax.plot(wavenumbers, gauss(wavenumbers, *popt))
                ax.set_title('Gauss Fit H %i'%i)
                ax.figure.canvas.draw()
        except Exception:
            print('Could not find appropriate Fit for component %s'%i)
        
        
        w_max = idx_max
        w_min = idx_min
        print('Recommended slice indices for W %.0f are %.0f and %.0f'%(i, w_min, w_max))
        relevant_index.append({'idx_min':w_min , 'idx':resonance_slice_idx, 'idx_max': w_max, 'max': slice_max})
        
        print('-'*3)
        """ old:
        left_margin=resonance_slice_idx-(initial_idx-idx_min)                           #new margins; same width but with real resonance as midpoint
        right_margin=resonance_slice_idx+(idx_max-initial_idx)
        relevant_index[i].update({'idx_min':left_margin , 'idx':resonance_slice_idx, 'idx_max': right_margin})
        """
        
        # print("deleting columns "+str(left_margin)+","+str(right_margin)+" from background noise")
    """check if the initial guess was wrong. look for higher intensity up to next resonance"""
    return seed_H, H_pixel, relevant_index


def gauss(x, A, x0, sigma):
    return A*np.exp(-(x-x0)**2/(2*sigma**2))

def find_nearest(array,value):
    idx=(np.abs(array-value)).argmin()
    return array[idx], idx


def find_slices(spec, threshold, imin=0, imax=-1):
    """
    Returns the min and max range around a maximum where intensity is above threshold

    Parameters
    ----------
    spec : np.array
        spectrum
    threshold : float
        0 < threshold <1.

    Returns
    -------
    w_min : int
    w_max : int
    """
    start = np.argmax(spec[imin:imax]) + imin
    epsilon = spec[start] * threshold
    w_min = w_max = start
    while spec[w_min] >= epsilon and w_min != 0:
        w_min-=1
    while spec[w_max] >= epsilon and w_max < len(spec)-1:
        w_max+=1
    return w_min, w_max

def convert_index_range(coords: dict, y_size: int):
    """
    Convert a range of x and y values to a list of indices.

    Parameters
    ----------
    coords: A dictionary that specifies a range of x and y values, where each key is either 'x' or 'y' and each value is a tuple of two integers 
        representing the thresholds for the area.
    y_size: An integer representing the size of the y axis.
    Returns
    -------
    A list of indices representing the corresponding positions in a 1-dimensional representation of a 2-dimensional grid.
    
    Example:
    
    coords = {'x': (1, 2), 'y': (3, 4)}
    y_size = 5
    
    result = convert_index_range(coords, y_size)
    
    print(result)
    [16, 17, 21, 22]
    """
    y = (coords['y'][0], coords['y'][1])
    x = (coords['x'][0], coords['x'][1])
    idx_list = []
    x_r = np.arange(x[0], x[1]+1, dtype=int)
    y_r = np.arange(y[0], y[1]+1, dtype=int)
    for yy in y_r:
        for xx in x_r:
            idx_list.append(xx+yy*y_size)
    return idx_list 
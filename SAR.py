"""
SAR reconstruction — single-file Python implementation.

Derives the monostatic SAR imaging algorithm, provides a synthetic data
generator for testing, an HDF5 importer, and an interactive depth slider.

Inspired by mrdvorsky's sar3d algorithm in MATLAB.

The algorithm reconstructs a 3D complex SAR image from a 2D frequency-stepped
xy-raster scan, in seven steps:
    1. Elementwise wavenumber from the frequency vector
    2. x/y sample spacing
    3. Spatial wavenumber grids
    4. Forward FFT over (x, y) with 1/k0 amplitude weight
    5. Dispersion relation + evanescent-mode removal
    6. Back-propagate to each depth and integrate over frequency
    7. Inverse FFT to form the image

Default units are mm and GHz (set by the speed of light C).
"""

import numpy as np
import matplotlib.pyplot as plt
import h5py
from matplotlib.widgets import Slider
C = 299.792458  # speed of light, mm/GHz units


# ---------------------------------------------------------------------------
# Core reconstruction
# ---------------------------------------------------------------------------
def sar3d(S, x, y, z, f):
    """Reconstruct a 3D SAR image from 2D raster-scan measurement data.

    Inputs:
        S - (Nx, Ny, F) complex measurement data. Value at (i, j, k) is the
            measurement at coordinate (x[i], y[j]) and frequency f[k].
        x - x-coordinate vector (length Nx).
        y - y-coordinate vector (length Ny).
        z - desired reconstruction depth vector (length Nz).
        f - frequency vector (length F).

    Output:
        Image - (Nx, Ny, Nz) complex SAR image.
    """
    # Step 1 — frequency -> wavenumber, on axis 2 to broadcast over (x, y)
    freq = np.asarray(f)
    k0 = np.multiply(2 * np.pi, freq)
    k0 = np.divide(k0, C)
    k0 = k0.reshape(1, 1, freq.size)

    # Step 2 — sample spacings
    x_arr = np.asarray(x)
    y_arr = np.asarray(y)
    z_arr = np.asarray(z)
    dx = np.subtract(x_arr[1], x_arr[0])
    dy = np.subtract(y_arr[1], y_arr[0])

    # Step 3 — spatial wavenumber grids (FFT order, angular wavenumbers)
    ix = S.shape[0]
    iy = S.shape[1]
    kx = 2 * np.pi * np.fft.fftfreq(ix, d=dx)
    ky = 2 * np.pi * np.fft.fftfreq(iy, d=dy)
    kx = kx.reshape(ix, 1, 1)
    ky = ky.reshape(1, iy, 1)

    # Step 4 — forward FFT over (x, y) with amplitude weight
    WarpedSpectrum = np.fft.fft2(S, axes=(0, 1)) / k0

    # Step 5 — dispersion relation; zero the evanescent (non-propagating) modes
    arg = 4 * k0**2 - kx**2 - ky**2
    kz = np.sqrt(np.maximum(arg, 0.0))
    WarpedSpectrum[kz == 0] = 0

    # Step 6 — back-propagate to each depth, integrate over frequency
    ImageSpectrum = np.zeros((ix, iy, z_arr.size), dtype=complex)
    for iz in range(z_arr.size):
        zi = np.abs(z_arr[iz])
        phase = np.exp(1j * kz * zi)
        ImageSpectrum[:, :, iz] = zi * np.mean(WarpedSpectrum * phase, axis=2)

    # Step 7 — inverse FFT back to (x, y)
    Image = np.fft.ifft2(ImageSpectrum, axes=(0, 1))

    return Image


# ---------------------------------------------------------------------------
# Synthetic data generator (for testing / validation)
# ---------------------------------------------------------------------------
def create_sar_data_3d(x, y, f, x0, y0, z0, a0=None):
  
    x_arr = np.asarray(x).reshape(-1, 1, 1)   # (Nx, 1, 1)
    y_arr = np.asarray(y).reshape(1, -1, 1)   # (1, Ny, 1)
    f_arr = np.asarray(f).reshape(1, 1, -1)   # (1, 1, F)

    x0 = np.atleast_1d(x0)
    y0 = np.atleast_1d(y0)
    z0 = np.atleast_1d(z0)
    if a0 is None:
        a0 = np.ones_like(x0, dtype=float)
    else:
        a0 = np.atleast_1d(a0)

    k = 2 * np.pi * f_arr / C                  # (1, 1, F)

    S = np.zeros((x_arr.size, y_arr.size, f_arr.size), dtype=complex)
    for i in range(x0.size):
        R = np.sqrt((x_arr - x0[i])**2 + (y_arr - y0[i])**2 + z0[i]**2)  # (Nx,Ny,1)
        S += a0[i] * np.exp(-1j * k * 2 * R) / (R**2)

    return S


# ---------------------------------------------------------------------------
# HDF5 import
# ---------------------------------------------------------------------------
def load_hdf5(fn):
  
    

    with h5py.File(fn, 'r') as h:
        S_flat = h['Data/S11_real'][:] + 1j * h['Data/S11_imag'][:]   # (Npts, F)
        xc = h['Coords/x_data'][:]
        yc = h['Coords/y_data'][:]
        f = h['Frequencies/Range'][:]

    ux = np.unique(np.round(xc, 6))
    uy = np.unique(np.round(yc, 6))
    Nx, Ny, F = len(ux), len(uy), len(f)

    # nearest-bin index for each measured point
    ix = np.abs(xc[:, None] - ux[None, :]).argmin(axis=1)
    iy = np.abs(yc[:, None] - uy[None, :]).argmin(axis=1)

    S = np.zeros((Nx, Ny, F), dtype=complex)
    S[ix, iy, :] = S_flat            # scatter-place, order-independent
    return S, ux, uy, f


# ---------------------------------------------------------------------------
# Interactive depth-slice viewer
# ---------------------------------------------------------------------------
def interactive_slicer(Image, x, y, z, cmap='viridis'):
    
    
 
    mag = np.abs(Image)             # (Nx, Ny, Nz)
    vmax = mag.max()                # global peak, fixed across slices
    iz0 = len(z) // 2
 
    # main image axes, with room at the bottom for the slider
    fig, ax = plt.subplots(figsize=(8, 8))
    fig.subplots_adjust(bottom=0.15)
 
    im = ax.imshow(mag[:, :, iz0].T, origin='lower',
                   extent=[x[0], x[-1], y[0], y[-1]],
                   vmin=0, vmax=vmax, cmap=cmap, aspect='equal')
    ax.set_xlabel('x (mm)'); ax.set_ylabel('y (mm)')
    ax.set_title(f'|Image|, z = {z[iz0]:.1f} mm')
    fig.colorbar(im, ax=ax, label='magnitude')
 
    # slider axes: [left, bottom, width, height] in figure fraction
    slider_ax = fig.add_axes([0.2, 0.04, 0.6, 0.03])
    depth_slider = Slider(slider_ax, 'depth idx', 0, len(z) - 1,
                          valinit=iz0, valstep=1)
 
    def update(val):
        iz = int(depth_slider.val)
        im.set_data(mag[:, :, iz].T)          # swap only the pixel data
        ax.set_title(f'|Image|, z = {z[iz]:.1f} mm')
        fig.canvas.draw_idle()
 
    depth_slider.on_changed(update)
 
    plt.show()
    return depth_slider
 

def show_slice_static(Image, x, y, z, iz=None, cmap='viridis'):

   
    mag = np.abs(Image)
    if iz is None:
        iz = int(np.unravel_index(np.argmax(mag), mag.shape)[2])

    plt.figure(figsize=(8, 8))
    plt.imshow(mag[:, :, iz].T, origin='lower',
               extent=[x[0], x[-1], y[0], y[-1]],
               vmin=0, vmax=mag.max(), cmap=cmap, aspect='equal')
    plt.xlabel('x (mm)'); plt.ylabel('y (mm)')
    plt.title(f'|Image|, z = {z[iz]:.1f} mm')
    plt.colorbar(label='magnitude')
    plt.tight_layout()
    plt.show()
    return iz


def _demo_synthetic():
   
    x = np.linspace(-50, 50, 101)
    y = np.linspace(-50, 50, 101)
    f = np.linspace(24, 40, 100)     # GHz
    z = np.linspace(1, 100, 100)     # depths

    S = create_sar_data_3d(x, y, f, x0=10, y0=-5, z0=50)
    Image = sar3d(S, x, y, z, f)

    mag = np.abs(Image)
    ix, iy, iz = np.unravel_index(np.argmax(mag), mag.shape)
    print(f"Synthetic target placed at (10, -5, 50)")
    print(f"Reconstructed peak at x={x[ix]:.1f}  y={y[iy]:.1f}  z={z[iz]:.1f} mm")
    return Image, x, y, z


def domain_coloring(Image, x, y, z, iz=None, gamma=0.6, legend=True):
    """Complex domain-coloring view of one depth slice.
 
    Maps the complex image to color: hue = phase,
    brightness = magnitude. A cyclic HSV hue is used so phase wraps.
 
    Args:
        Image - (Nx, Ny, Nz) complex reconstruction from sar3d.
        x, y, z - coordinate vectors.
        iz    - depth index to show; if None, uses the strongest-return slice.
        gamma - brightness gamma (<1 lifts weak returns; 0.6 is a good start).
        legend - draw a phase colorwheel inset.
 
    Returns the depth index shown.
    """
    from matplotlib.colors import hsv_to_rgb
 
    mag = np.abs(Image)
    if iz is None:
        iz = int(np.unravel_index(np.argmax(mag), mag.shape)[2])
 
    sl = Image[:, :, iz]
    M = np.abs(sl)
    M = M / (M.max() + 1e-12)
    P = np.angle(sl)                          # -pi..pi
 
    H = (P + np.pi) / (2 * np.pi)             # phase -> hue in 0..1
    V = M**gamma                              # magnitude -> brightness
    rgb = hsv_to_rgb(np.stack([H, np.ones_like(H), V], axis=-1))
 
    fig = plt.figure(figsize=(10, 8.5))
    ax = fig.add_axes([0.08, 0.07, 0.84, 0.86])
    ax.imshow(np.transpose(rgb, (1, 0, 2)), origin='lower',
              extent=[x[0], x[-1], y[0], y[-1]], aspect='equal')
    ax.set_xlabel('x (mm)'); ax.set_ylabel('y (mm)')
    ax.set_title(f'Complex domain coloring  (z = {z[iz]:.1f} mm)\n'
                 f'hue = phase   brightness = magnitude', fontsize=12)
 
    if legend:
        wheel = fig.add_axes([0.79, 0.76, 0.16, 0.16], projection='polar')
        th = np.linspace(0, 2 * np.pi, 360)
        r = np.linspace(0.6, 1.0, 20)
        TH, _ = np.meshgrid(th, r)
        wrgb = hsv_to_rgb(np.stack(
            [TH / (2 * np.pi), np.ones_like(TH), np.ones_like(TH)], axis=-1))
        wheel.pcolormesh(th, r, TH, color=wrgb.reshape(-1, 3), shading='auto')
        wheel.set_yticklabels([]); wheel.set_xticklabels([])
        wheel.set_title('phase', fontsize=8, pad=2)
        wheel.grid(False)
 
    plt.show()
    return iz


if __name__ == "__main__":
   
    S, x, y, f = load_hdf5("ScanFile_2026-02-12_13_55_26_391464.hdf5")

    S = S - S.mean(axis=(0, 1), keepdims=True)
    z = np.linspace(1, 2, 10)
    Image = sar3d(S, x, y, z, f)
    interactive_slicer(Image, x, y, z)
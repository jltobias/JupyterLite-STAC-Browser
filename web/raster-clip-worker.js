/* Dependencies are loaded only after the user starts a crop. */
importScripts('./vendor/geotiff-3.0.5.js', './vendor/proj4-2.19.10.js');
self.onmessage = async ({data}) => {
  try {
    const {clipRaster} = await import('./raster-clip.js');
    const value = await clipRaster(data, {GeoTIFF: self.GeoTIFF, proj4: self.proj4,
      progress: value => self.postMessage({type: 'progress', value})});
    self.postMessage({type: 'result', value}, [value.buffer]);
  } catch (error) { self.postMessage({type: 'error', message: error.message}); }
};

import {bboxValue} from './stac.js';
import {rectangleGeometry} from './geometry.js';

// Verified against the CDSE NDVI 300m 10-daily V2 band table and Browser deep links.
const DATASET = 'COPERNICUS_CLMS_NDVI_300M_10DAILY_V2';
const BANDS = {ndvi: ['NDVI', 'UINT8'], nobs: ['NOBS', 'UINT8'], qflag: ['QFLAG', 'UINT8'], unc: ['UNC', 'INT16']};
export function copernicusSubset(item, key, asset) {
  const collection = item.collection;
  if (collection === 'clms_ndvi_global_300m_10daily_v2_nc') return {unavailable: 'NetCDF clipping unavailable: the verified NDVI V2 provider subset route produces GeoTIFF only. Keep the original .nc download; no conversion is offered.'};
  if (collection !== 'clms_ndvi_global_300m_10daily_v2_cog' || !Object.hasOwn(BANDS, key) || /netcdf|\.nc(?:\b|$)/i.test(`${asset.type || ''} ${asset.href}`)) return null;
  const date = item.properties?.datetime;
  if (typeof date !== 'string' || !/^\d{4}-\d\d-\d\dT/.test(date) || !Number.isFinite(Date.parse(date))) return {unavailable: 'Provider subset unavailable: this Item has no verified acquisition date. Use its original file access.'};
  const day = new Date(date).toISOString().slice(0, 10);
  const [band, sampleType] = BANDS[key];
  const evalscript = `//VERSION=3\nfunction setup() { return {input: [{bands: ["${band}"], units: "DN"}], output: {bands: 1, sampleType: "${sampleType}"}}; }\nfunction evaluatePixel(sample) { return [sample.${band}]; }`;
  return {band, sampleType, date: day, create(bbox) {
    bbox = bboxValue(bbox);
    const [west, south, east, north] = bbox;
    const params = new URLSearchParams({datasetId: DATASET, clmsSelectedCollection: DATASET, clmsSelectedPath: 'Vegetation Indices',
      panel: 'layers', themeId: 'DEFAULT-THEME', lat: String((south + north) / 2), lng: String((west + east) / 2),
      zoom: String(Math.max(1, Math.min(18, Math.floor(Math.log2(360 / Math.max(east - west, north - south)))))),
      dateMode: 'SINGLE', fromTime: day + 'T00:00:00.000Z', toTime: day + 'T23:59:59.999Z',
      upsampling: 'NEAREST', downsampling: 'NEAREST', evalscript: btoa(evalscript)});
    return {url: 'https://browser.dataspace.copernicus.eu/?' + params,
      aoi: {type: 'FeatureCollection', features: [{type: 'Feature', properties: {item_id: item.id, collection, date: day, band, bbox}, geometry: rectangleGeometry(bbox)}]}};
  }};
}

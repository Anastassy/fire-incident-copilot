// Presentation labels only: source records and their provenance stay unchanged.
const scenarios = {
  normal: '01 · Baseline recordings',
  escalation: '02 · Changing readings',
  degraded: '03 · Connectivity loss',
  'palisades-full': 'Palisades · 10-minute recording',
  'palisades-focus': 'Palisades · 3:26 · key excerpt',
  'base2-palisades-v1': 'Base2 × Palisades · 3:26 · two CCTV cameras',
};
const devices = {
  'TMP-B2-GRADAS': 'Temperature · Gradas',
  'TMP-B2-GALLERY': 'Temperature · gallery',
  'TMP-B2-COWORK': 'Temperature · coworking',
  'SMK-B2-GRADAS': 'Smoke · Gradas',
  'SMK-B2-GALLERY': 'Smoke · gallery',
  'SMK-B2-COWORK': 'Smoke · coworking',
  'PWR-B2-GRADAS': 'Lighting and smoke sensor power',
  'CAM-B2-GRADAS': 'Gradas · synthetic CCTV',
  'CAM-B2-GALLERY': 'Gallery · synthetic CCTV',
  'ACCESS-B2-GRADAS': 'Gradas badge reader',
  'RADIO-B2-PALISADES': 'Palisades · archived radio',
};
const deviceKinds = {
  temperature_sensor: 'Temperature sensor', smoke_sensor: 'Smoke sensor',
  camera: 'Camera', access_reader: 'Badge reader', radio_channel: 'Radio channel',
  multisensor: 'Multisensor',
};
export const scenarioName = scenario => scenarios[scenario?.scenario_id] || scenario?.scenario_id || 'Scenario';
export const deviceName = device => devices[device?.device_id] || (device ? `${deviceKinds[device.kind] || 'Source'} · ${device.device_id}` : 'Source');

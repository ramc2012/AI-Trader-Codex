const rawBase = process.env.NEXT_PUBLIC_APP_NAME_BASE || 'NiftyTraderGravity';
const rawInstance = process.env.NEXT_PUBLIC_APP_INSTANCE_LABEL || 'LOCAL';

export const APP_NAME_BASE = rawBase.trim() || 'NiftyTraderGravity';
export const APP_INSTANCE_LABEL = rawInstance.trim().toUpperCase() || 'LOCAL';
export const APP_DISPLAY_NAME = `${APP_NAME_BASE} ${APP_INSTANCE_LABEL}`.trim();

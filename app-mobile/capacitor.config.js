/** @type {import('@capacitor/cli').CapacitorConfig} */

const isIos = process.env.CAPACITOR_PLATFORM === 'ios';

const config = {
  appId: 'com.km220.openems',
  appName: '220 EMS',
  webDir: 'www',
  server: {
    url: 'https://220-km.com:9220',
    androidScheme: 'https',
    cleartext: false,
    allowNavigation: isIos ? ['220-km.com', '220-km-preprod.com'] : ['220-km.com'],
  },
  ios: {
    contentInset: 'automatic',
    allowsLinkPreview: false,
    scrollEnabled: true,
  },
};

module.exports = config;

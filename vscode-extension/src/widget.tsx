/* eslint-disable */
import React, { useEffect } from 'react';
import { injectGeoGebraApplet } from '../../src/shared/createApplet';

export interface GeoGebraWidgetProps {
  elementId?: string;
  appName?: string;
  width?: number;
  height?: number;
}

export const GeoGebraWidget: React.FC<GeoGebraWidgetProps> = ({
  elementId = 'ggb-element-debug',
  appName = 'suite',
  width = 800,
  height = 600
}) => {
  useEffect(() => {
    const { appletPromise, cleanup } = injectGeoGebraApplet({
      elementId,
      appName,
      width,
      height,
      scaleContainerClass: 'applet-wrapper',
      allowUpscale: false,
      appletOnLoad: null
    });

    // Optionally act on the created applet
    let mounted = true;
    appletPromise.then((applet) => {
      if (!mounted) return;
      console.log('GeoGebra applet injected (react via shared helper)');
    }).catch((e) => console.error('Applet injection failed', e));

    return () => {
      mounted = false;
      try {
        const el = document.getElementById(elementId);
        if (el) el.innerHTML = '';
        const winApplet = (window as any).ggblab_applet;
        if (winApplet && typeof winApplet.remove === 'function') {
          try { winApplet.remove(); } catch (e) { /* ignore */ }
        }
        delete (window as any).ggblab_applet;
        if (typeof cleanup === 'function') {
          try { cleanup(); } catch (e) { console.error('cleanup failed', e); }
        }
      } catch (e) {
        // ignore
      }
    };
  }, [elementId, appName, width, height]);

  return (
    <div id={elementId} className="applet-wrapper" style={{ width, height }} />
  );
};

export default GeoGebraWidget;

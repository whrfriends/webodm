/**
 * Minimal React wrapper. React renders an empty mount div once,
 * then vanilla JS in main.js takes over via window.roadAttributesInit.
 */
import React from 'react';
import ReactDOM from 'react-dom';
import PluginsAPI from '../../../../classes/plugins/API';

class RoadAttributesApp extends React.Component {
  componentDidMount() {
    // Hand off to the vanilla entry. main.js exports this on window.
    if (typeof window.roadAttributesInit === 'function') {
      window.roadAttributesInit({ mountEl: this.refs.mount });
    } else {
      // main.js not loaded yet — wait briefly.
      let tries = 0;
      const t = setInterval(() => {
        tries++;
        if (typeof window.roadAttributesInit === 'function') {
          clearInterval(t);
          window.roadAttributesInit({ mountEl: this.refs.mount });
        } else if (tries > 40) {
          clearInterval(t);
          console.error('roadAttributesInit never appeared on window');
        }
      }, 100);
    }
  }
  render() {
    return React.createElement('div', {
      id: 'ra-app-mount',
      ref: 'mount',
      style: { width: '100%', height: '100%' }
    });
  }
}

PluginsAPI.App.ready({
  component: RoadAttributesApp
});

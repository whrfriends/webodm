import L from 'leaflet';
import ReactDOM from 'ReactDOM';
import React from 'React';
import PropTypes from 'prop-types';
import { _ } from 'webodm/classes/gettext';
import './Changedetect.scss';
import ChangedetectPanel from './ChangedetectPanel';

class ChangedetectButton extends React.Component {
  static propTypes = {
    tasks: PropTypes.object.isRequired,
    map: PropTypes.object.isRequired,
    outer: PropTypes.object  // optional ref to outer leaflet container
  }

  constructor(props){
    super(props);
    this.state = { showPanel: false };
  }

  handleOpen = () => { this.setState({ showPanel: true }); };
  handleClose = () => { this.setState({ showPanel: false }); };

  // After mount, also toggle the 'open' class on the outer leaflet container
  // (.leaflet-control-changedetect) so the SCSS rule
  //   .leaflet-control-changedetect.open .changedetect-panel { display: block; }
  // matches. We can't put the class on the container via React (it owns it),
  // so we manipulate the DOM imperatively.
  componentDidMount(){
      // Sync initial state to the outer leaflet container class.
      this.syncOpenClass();
  }

  componentDidUpdate(){
      this.syncOpenClass();
  }

  syncOpenClass(){
      if (this.props.outer){
          if (this.state.showPanel) this.props.outer.classList.add('open');
          else this.props.outer.classList.remove('open');
      }
  }

  render(){
    const { showPanel } = this.state;
    return (<div className={showPanel ? "open" : ""}>
        <a href="javascript:void(0);"
            onClick={this.handleOpen}
            title={_("Change Detection")}
            className="leaflet-control-changedetect-button leaflet-bar-part theme-secondary"></a>
        <ChangedetectPanel map={this.props.map}
                           isShowed={showPanel}
                           tasks={this.props.tasks}
                           onClose={this.handleClose} />
    </div>);
  }
}

export default L.Control.extend({
    options: { position: 'topright' },

    onAdd: function (map) {
        var container = L.DomUtil.create('div', 'leaflet-control-changedetect leaflet-bar leaflet-control');
        L.DomEvent.disableClickPropagation(container);
        // Keep a direct DOM ref to the leaflet container so React can toggle
        // the 'open' class on the OUTER element (SCSS targets the outer container).
        // The ref is read by ChangedetectButton.componentDidUpdate().
        this._outerContainer = container;
        ReactDOM.render(
            <ChangedetectButton map={this.options.map} tasks={this.options.tasks} outer={this._outerContainer} />,
            container
        );
        return container;
    }
});

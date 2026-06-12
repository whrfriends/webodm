import React from 'React';
import L from 'leaflet';
import $ from 'jquery';

export default class FlightPlanner extends React.Component {
    constructor(props) {
        super(props);
        this.state = {
            waypoints: [],
            polygonCoords: [],
            drawMode: false,
            gridSettings: { altitude: 60, overlap: 75, sidelap: 70, angle: 0, speed: 5 },
            selectedWaypointIndex: null,
            missionStats: { distance: 0, duration: 0 }
        };
        this.map = null;
        this.polyLayer = null;
        this.pathLayer = null;
        this.markers = [];
    }

    componentDidMount() {
        this.initMap();
        [500, 1500, 3000].forEach(d => setTimeout(() => this.map && this.map.invalidateSize(), d));
    }

    initMap() {
        this.map = L.map('planner-map', { zoomControl: false, attributionControl: false })
            .setView([22.54, 114.05], 13);
        
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { 
            maxZoom: 19
        }).addTo(this.map);
        
        L.control.zoom({ position: 'bottomright' }).addTo(this.map);

        this.map.on('click', (e) => {
            if (this.state.drawMode) this.addPolygonVertex(e.latlng.lat, e.latlng.lng);
            else this.addWaypoint(e.latlng.lat, e.latlng.lng);
        });

        this.map.locate({setView: true, maxZoom: 16});
        
        delete L.Icon.Default.prototype._getIconUrl;
        L.Icon.Default.mergeOptions({
            iconRetinaUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon-2x.png',
            iconUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon.png',
            shadowUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
        });
    }

    addPolygonVertex(lat, lng) {
        this.setState(prevState => ({ polygonCoords: [...prevState.polygonCoords, [lng, lat]] }), this.renderPolygon);
    }

    renderPolygon = () => {
        if (this.polyLayer) this.map.removeLayer(this.polyLayer);
        const latlngs = this.state.polygonCoords.map(c => [c[1], c[0]]);
        if (latlngs.length > 0) this.polyLayer = L.polygon(latlngs, {color: '#f39c12', weight: 2, fillOpacity: 0.15}).addTo(this.map);
    }

    addWaypoint(lat, lng) {
        const wp = { lat, lng, altitude: this.state.gridSettings.altitude, heading: 0, gimbalPitch: -90 };
        this.setState(prevState => ({ waypoints: [...prevState.waypoints, wp], selectedWaypointIndex: prevState.waypoints.length }), () => { this.renderPath(); this.calculateStats(); });
    }

    renderPath = () => {
        if (this.pathLayer) this.map.removeLayer(this.pathLayer);
        this.markers.forEach(m => this.map.removeLayer(m));
        this.markers = [];
        const latlngs = this.state.waypoints.map(wp => [wp.lat, wp.lng]);
        if (latlngs.length > 1) this.pathLayer = L.polyline(latlngs, {color: '#3498db', weight: 3, dashArray: '5, 10'}).addTo(this.map);
        this.state.waypoints.forEach((wp, index) => {
            const icon = L.divIcon({
                className: 'custom-wp-icon',
                html: `<div style="background:#3498db; color:white; border-radius:50%; width:24px; height:24px; text-align:center; line-height:24px; font-size:12px; border:2px solid white; font-weight:bold;">${index + 1}</div>`,
                iconSize: [24, 24]
            });
            const marker = L.marker([wp.lat, wp.lng], { draggable: true, icon: icon }).addTo(this.map);
            marker.on('click', (e) => { L.DomEvent.stopPropagation(e); this.setState({ selectedWaypointIndex: index }); });
            marker.on('dragend', (e) => this.updateWaypoint(index, { lat: e.target.getLatLng().lat, lng: e.target.getLatLng().lng }));
            this.markers.push(marker);
        });
    }

    updateWaypoint(index, updates) {
        this.setState(prevState => {
            const wps = [...prevState.waypoints];
            wps[index] = { ...wps[index], ...updates };
            return { waypoints: wps };
        }, () => { this.renderPath(); this.calculateStats(); });
    }

    calculateStats = () => {
        let dist = 0;
        for (let i = 0; i < this.state.waypoints.length - 1; i++) {
            dist += L.latLng(this.state.waypoints[i]).distanceTo(L.latLng(this.state.waypoints[i+1]));
        }
        this.setState({ missionStats: { distance: dist.toFixed(0), duration: (dist / this.state.gridSettings.speed / 60).toFixed(1) } });
    }

    generateGrid = () => {
        if (this.state.polygonCoords.length < 3) return;
        const polygon = [ [...this.state.polygonCoords, this.state.polygonCoords[0]] ];
        $.ajax({
            url: 'generate_grid/', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({ polygon, ...this.state.gridSettings }),
            success: (data) => this.setState({ waypoints: data.waypoints, drawMode: false, selectedWaypointIndex: null }, () => { this.renderPath(); this.calculateStats(); }),
            error: (xhr) => alert('Error: ' + (xhr.responseJSON ? xhr.responseJSON.error : 'Network Error'))
        });
    }

    exportToLitchi() {
        if (this.state.waypoints.length === 0) return;
        let csv = 'latitude,longitude,altitude(m),heading(deg),curvesize(m),rotationdir,gimbalmode,gimbalpitchangle,actiontype1,actionparam1,actiontype2,actionparam2,actiontype3,actionparam3,actiontype4,actionparam4,actiontype5,actionparam5,actiontype6,actionparam6,actiontype7,actionparam7,actiontype8,actionparam8,actiontype9,actionparam9,actiontype10,actionparam10,actiontype11,actionparam11,actiontype12,actionparam12,actiontype13,actionparam13,actiontype14,actionparam14,actiontype15,actionparam15\n';
        this.state.waypoints.forEach(wp => {
            csv += `${wp.lat},${wp.lng},${wp.altitude},${wp.heading},0,0,0,${wp.gimbalPitch},-1,0,-1,0,-1,0,-1,0,-1,0,-1,0,-1,0,-1,0,-1,0,-1,0,-1,0,-1,0,-1,0,-1,0,-1,0\n`;
        });
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = 'mission.csv'; a.click();
    }

    render() {
        const { waypoints, selectedWaypointIndex, gridSettings, drawMode, missionStats } = this.state;
        const selectedWp = selectedWaypointIndex !== null ? waypoints[selectedWaypointIndex] : null;

        return (
            <div style={{ display: 'flex', width: '100%', height: '100%', background: '#1c1c1c' }}>
                <div style={{ width: '300px', background: '#252525', display: 'flex', flexDirection: 'column', borderRight: '1px solid #333', zIndex: 1100, color: '#fff', padding: '15px' }}>
                    <h2 style={{ fontSize: '18px', color: '#3498db', marginBottom: '20px' }}>MISSION HUB</h2>
                    <button className={`btn btn-block btn-sm ${drawMode ? 'btn-danger' : 'btn-primary'}`} style={{ marginBottom: '15px' }} onClick={() => this.setState({ drawMode: !drawMode })}>
                        {drawMode ? 'STOP DRAWING' : 'DRAW AREA'}
                    </button>
                    <div style={{ background: '#333', padding: '10px', borderRadius: '4px', marginBottom: '15px' }}>
                        <label style={{ fontSize: '12px' }}>Altitude: {gridSettings.altitude}m</label>
                        <input type="range" min="10" max="150" value={gridSettings.altitude} className="form-control-range" onChange={e => this.setState({ gridSettings: { ...gridSettings, altitude: parseInt(e.target.value) }})} />
                        <button className="btn btn-success btn-sm btn-block mt-3" onClick={this.generateGrid}>GENERATE GRID</button>
                    </div>
                    <div style={{ flex: 1, overflowY: 'auto' }}>
                        {waypoints.map((wp, i) => (
                            <div key={i} style={{ padding: '8px', borderBottom: '1px solid #333', background: selectedWaypointIndex === i ? '#3498db' : 'transparent', cursor: 'pointer', fontSize: '11px' }} onClick={() => this.setState({ selectedWaypointIndex: i })}>
                                {i+1}. {wp.lat.toFixed(6)}, {wp.lng.toFixed(6)}
                            </div>
                        ))}
                    </div>
                    <button className="btn btn-primary btn-block mt-3" onClick={() => this.exportToLitchi()} disabled={waypoints.length === 0}>EXPORT CSV</button>
                </div>
                <div style={{ flex: 1, position: 'relative' }}>
                    <div id="planner-map" style={{ width: '100%', height: '100%', position: 'absolute' }}></div>
                    <div style={{ position: 'absolute', bottom: '20px', left: '20px', background: 'rgba(0,0,0,0.7)', padding: '10px', borderRadius: '4px', zIndex: 1050, color: '#fff', fontSize: '12px' }}>
                        DIST: {missionStats.distance}m | TIME: {missionStats.duration}m | WP: {waypoints.length}
                    </div>
                    {selectedWp && (
                        <div style={{ position: 'absolute', top: '20px', right: '20px', width: '200px', background: 'rgba(37,37,37,0.9)', padding: '15px', borderRadius: '6px', zIndex: 1060, color: '#fff' }}>
                            <div style={{ marginBottom: '10px', fontWeight: 'bold', color: '#3498db' }}>WP {selectedWaypointIndex + 1}</div>
                            <label style={{ fontSize: '11px' }}>Alt (m)</label>
                            <input type="number" value={selectedWp.altitude} className="form-control form-control-sm" style={{ background: '#1c1c1c', color: '#fff', border: 'none' }} onChange={e => this.updateWaypoint(selectedWaypointIndex, { altitude: parseInt(e.target.value) })} />
                            <button className="btn btn-danger btn-xs btn-block mt-3" onClick={() => { const n = waypoints.filter((_, i) => i !== selectedWaypointIndex); this.setState({ waypoints: n, selectedWaypointIndex: null }, () => { this.renderPath(); this.calculateStats(); }); }}>DELETE</button>
                        </div>
                    )}
                </div>
            </div>
        );
    }
}

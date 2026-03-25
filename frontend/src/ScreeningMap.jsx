import { MapContainer, TileLayer, Marker, Circle, Popup, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { useEffect } from "react";
import "leaflet/dist/leaflet.css";

// Fix default marker icons for Vite/React
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

function FlyToLocation({ lat, lon }) {
  const map = useMap();

  useEffect(() => {
    const latNum = Number(lat);
    const lonNum = Number(lon);

    if (!Number.isFinite(latNum) || !Number.isFinite(lonNum)) return;

    map.flyTo([latNum, lonNum], 13, {
      duration: 1.5,   // animation speed in seconds
      easeLinearity: 0.25, // easing function for smoother animation
    });
  }, [lat, lon, map]);

  return null;
}

function ZoomToRadius({ radiusMiles }) {
  const map = useMap();

  useEffect(() => {
    const r = Number(radiusMiles);
    if (!Number.isFinite(r) || r <= 0) return;

    let zoom;


    if (r < 0.5) zoom = 15;
    else if (r < 1) zoom = 14;
    else if (r < 2) zoom = 13;
    else if (r < 4) zoom = 12;
    else if (r < 7) zoom = 11;
    else if (r < 10) zoom = 10;
    else if (r < 15) zoom = 9;
    else zoom = 11;

    map.setZoom(zoom);
  }, [radiusMiles, map]);

  return null;
}

function MapClickHandler({ onPickLocation }) {
  useMapEvents({
    click(e) {
      onPickLocation(e.latlng.lat, e.latlng.lng);
    },
  });

  return null;
}

export default function ScreeningMap({
  lat,
  lon,
  radiusMiles,
  onPickLocation,
}) {
  const latNum = Number(lat);
  const lonNum = Number(lon);
  const radiusMeters = (Number(radiusMiles) || 0) * 1609.34;

  const hasCoords = Number.isFinite(latNum) && Number.isFinite(lonNum);
  const center = hasCoords ? [latNum, lonNum] : [39.8283, -98.5795];

  return (
    <div className="map-shell">
      <MapContainer
        center={center}
        zoom={13}
        scrollWheelZoom={true}
        className="screening-map"
      >
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <FlyToLocation lat={latNum} lon={lonNum} />
        <ZoomToRadius radiusMiles={radiusMiles} />
        <MapClickHandler onPickLocation={onPickLocation} />

        {hasCoords && (
          <>
            <Marker 
                position={[latNum, lonNum]}
                draggable={true}
                eventHandlers={{
                dragend: (e) => {
                const pos = e.target.getLatLng();
                onPickLocation(pos.lat, pos.lng);
                },
              }}
            />
            
            {radiusMeters > 0 && (
              <Circle
                center={[latNum, lonNum]}
                radius={radiusMeters}
              />
            )}
          </>
        )}
      </MapContainer>
    </div>
  );
}



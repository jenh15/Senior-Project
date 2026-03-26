import { useMemo, useState, useRef, useEffect } from "react";
import { Toaster, toast } from "react-hot-toast";
import "leaflet/dist/leaflet.css";
import ScreeningMap from "./ScreeningMap";
import gbifLogo from "./assets/gbif-dot-org-green-logo.svg";
import inhsLogo from "./assets/dnr-nav-logo.jpeg";
import ourLogo from "./assets/environment_screening_logo.png";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";
const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || "";

const initialForm = { // SIUE engineering building
  address: "Engineering Building, Southern Illinois University Edwardsville",
  lat: "38.792170",
  lon: "-90.001636",
  radius_miles: "2"
};

export default function App() {
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState({
      general: "",
      addressLookup: "",
      coordinateLookup: "",
      environmentScan: "",
  });
  const lastToastRef = useRef("");
  useEffect(() => { // Convert err to toast notification
  const message =
    error.general ||
    error.addressLookup ||
    error.coordinateLookup ||
    error.environmentScan;

  if (message && message !== lastToastRef.current) {
    lastToastRef.current = message;
    showToast(message, "error");
  }
}, [error]);
  const [cooldowns, setCooldowns] = useState({
  addressLookup: 0,
  coordinateLookup: 0,
  environmentScan: 0,
});
  const [inputMode, setInputMode] = useState("address");
  const [hasScanned, setHasScanned] = useState(false);
  const [data, setData] = useState({
    gbif_hits: [],
    species_context: []
  });
  const [jobId, setJobId] = useState(null); 
  const [progress, setProgress] = useState(0);
  const [stepText, setStepText] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");

  const [notifications, setNotifications] = useState([]);

  const turnstileRef = useRef(null);
  const widgetIdRef = useRef(null);

  const backendUrl = useMemo(() => {
    if (!API_BASE_URL) return "";
    return API_BASE_URL.replace(/\/$/, "");
  }, []);


  useEffect(() => {
    if (!window.turnstile || !turnstileRef.current || !TURNSTILE_SITE_KEY) return;

    if (widgetIdRef.current !== null) return;

    widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
      sitekey: TURNSTILE_SITE_KEY,
      callback: (token) => {
        setCaptchaToken(token);
      },
      "expired-callback": () => {
        setCaptchaToken("");
      },
      "error-callback": () => {
        setCaptchaToken("");
      },
    });
    }, []);

  useEffect(() => {
    const interval = setInterval(() => {
    setCooldowns((prev) => {
      const updated = { ...prev };

      Object.keys(updated).forEach((key) => {
        if (updated[key] > 0) updated[key] -= 1;
      });

      return updated;
    });
    }, 1000);

    return () => clearInterval(interval);
  }, []);


function updateField(event) {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    resetResults();
  }

function setGeneralError(message) {
  setError((prev) => ({
    ...prev,
    general: message,
  }));
}

function clearGeneralError() {
  setErrors((prev) => ({
    ...prev,
    general: "",
  }));
}

const validateInputs = () => {
  const lat = parseFloat(form.lat);
  const lon = parseFloat(form.lon);

  if (isNaN(lat) || isNaN(lon)) {
    setGeneralError("Latitude and longitude must be numeric");
    return false;
  }

  if (lat < -90 || lat > 90) {
    setGeneralError("Latitude must be between -90 and 90");
    return false;
  }

  if (lon < -180 || lon > 180) {
    setGeneralError("Longitude must be between -180 and 180");
    return false;
  }

  if (isNaN(parseFloat(form.radius_miles)) || parseFloat(form.radius_miles) < 0 || parseFloat(form.radius_miles) > 100) {
    setGeneralError("Radius must be a positive number and less than 100 miles");
    return false;
  }

  return true;
};

async function checkApiResponse(response, action) {
    if (response.ok) return response;

    if (response.status === 429) {
      const retryAfter = response.headers.get("Retry-After");
      handleRateLimit(action, retryAfter);
      throw new Error("Rate limited");
    }

    const text = await response.text();
    throw new Error(text || "Request failed.");
  }

function handleRateLimit(action, retryAfter = null) {
  const fallback = {
    addressLookup: 60,
    coordinateLookup: 60,
    environmentScan: 3600,
  };

  const labels = {
    addressLookup: "Address lookup",
    coordinateLookup: "Coordinate lookup",
    environmentScan: "Environment scan",
  };

  const seconds = retryAfter ? parseInt(retryAfter, 10) : fallback[action];

  setCooldowns((prev) => ({
    ...prev,
    [action]: seconds,
  }));

  setError((prev) => ({
    ...prev,
    [action]: `${labels[action]} is rate limited. Try again in ${formatCooldown(seconds)}`,
  }));

  // showToast("Rate limited. Try again later.", "error");
}

function formatCooldown(seconds) {
  if (seconds >= 3600) {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  }

  if (seconds >= 60) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  }

  return `${seconds}s`;
}

function pollScanStatus(scanJobId) {
  const interval = setInterval(async () => {
    try {
      const statusResponse = await fetch(`${backendUrl}/scan/status/${scanJobId}`);

      if (!statusResponse.ok) {
        throw new Error("Failed to fetch scan status.");
      }

      const statusJson = await statusResponse.json();

      setProgress(statusJson.progress || 0);
      setStepText(statusJson.step || "Processing...");

      if (statusJson.status === "complete") {
        clearInterval(interval);
        setData(statusJson.result);
        setLoading(false);
        showToast("Environmental screen completed.", "success");
      }

      if (statusJson.status === "error") {
        clearInterval(interval);
        setGeneralError("Scan failed.");
        setLoading(false);
      }
    } catch (err) {
      clearInterval(interval);
      setGeneralError("Polling failed.");
      setLoading(false);
    }
  }, 1000); // Poll every 1 second
}

async function handleAddressLookup() {
  try {
    setError((prev) => ({ ...prev, addressLookup: "" }));

    if (!form.address.trim()) {
      throw new Error("Please enter an address.");
    }

    const response = await fetch(
      `${backendUrl}/geocode/search?q=${encodeURIComponent(form.address)}`
    );

    await checkApiResponse(response, "addressLookup");

    const data = await response.json();

    if (!data.best_match) {
      throw new Error("No matching address found.");
    }

    const best = data.best_match;

    setForm((prev) => ({
      ...prev,
      address: best.label || prev.address,
      lat: String(best.lat),
      lon: String(best.lon),
    }));
    resetResults();
    // later:
    // update map center / marker here
  } catch (err) {
      if (err.message !== "Rate limited") {
      setError((prev) => ({
        ...prev,
        addressLookup: err.message,
      }));
    }
    //showToast("Error occurred while looking up address.", "error");
  }
}

async function handleCoordinateLookup() {
  try {
    setError((prev) => ({ ...prev, coordinateLookup: "" }));

    const lat = Number(form.lat);
    const lon = Number(form.lon);

    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      throw new Error("Latitude and longitude must be numeric.");
    }

    const response = await fetch(
      `${backendUrl}/geocode/reverse?lat=${lat}&lon=${lon}`
    );

    await checkApiResponse(response, "coordinateLookup");

    const data = await response.json();

    if (!data.best_match) {
      throw new Error("No address found for those coordinates.");
    }

    const best = data.best_match;

    setForm((prev) => ({
      ...prev,
      address: best.label || prev.address,
      lat: String(best.lat),
      lon: String(best.lon),
    }));
    resetResults();

    // later:
    // update map center / marker here
  } catch (err) {
      if (err.message !== "Rate limited") {
        setError((prev) => ({
          ...prev,
          coordinateLookup: err.message,
        }));
      }
      //showToast("Error occurred while looking up coordinates.", "error");
  }
}

function resetResults() {
  setError({general: "", addressLookup: "", coordinateLookup: "", environmentScan: "" });
  setHasScanned(false);
  setData({
    gbif_hits: [],
    species_context: [],
  });
  setJobId(null);
  setProgress(0);
  setStepText("");
}

function showToast(message, type = "error") {
  if (!message) return;

  pushNotification(message, type);

  if (type === "success") return toast.success(message);
  if (type === "loading") return toast.loading(message);
  toast.error(message || "An error occurred");

}

function pushNotification(message, type = "error") {
  const item = {
    id: Date.now() + Math.random(),
    message,
    type,
    createdAt: new Date().toLocaleTimeString(),
  };

  setNotifications((prev) => [item, ...prev].slice(0, 20));
}

async function handleSubmit(event) {
    event.preventDefault();
    setError({ general: "", addressLookup: "", coordinateLookup: "", environmentScan: "" });
    setData({ gbif_hits: [], species_context: [] });
    setLoading(true);
    setHasScanned(true);
    setProgress(0);
    setStepText("Starting scan...");

    try {
      if (!backendUrl) {
        throw new Error("Missing VITE_API_BASE_URL. Add it to a .env file.");
      }
      if (!TURNSTILE_SITE_KEY) {
        throw new Error("Missing VITE_TURNSTILE_SITE_KEY. Add it to a .env file.");
      }
      if (!validateInputs()) {
        setLoading(false);
        return;
      }
      if (!captchaToken) {
        throw new Error("Please complete CAPTCHA");
      }
      const startResponse = await fetch(`${backendUrl}/scan/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          lat: Number(form.lat),
          lon: Number(form.lon),
          radius_miles: Number(form.radius_miles),
          captcha_token: captchaToken
        })
      });

      await checkApiResponse(startResponse, "environmentScan");

      const startJson = await startResponse.json();
      const newJobID = startJson.job_id;

      if (!newJobID) {
        throw new Error("Backend did not return a job ID");
      }

      setJobId(newJobID);

      if (window.turnstile && widgetIdRef.current !== null) {
        window.turnstile.reset(widgetIdRef.current);
      }
      setCaptchaToken("");

      // Polling loop
      pollScanStatus(newJobID);

    } catch (err) {
        if (err.message !== "Rate limited") {
        setError((prev) => ({
          ...prev,
          environmentScan: err.message,
        }));
      }
      //showToast("Error occurred while starting environment scan.", "error");
      setLoading(false);
    }
  }

  // Start of page render
  return (
    <>
    <Toaster
      position="top-right"
      toastOptions={{
        duration: 7000,
        style: {
          borderRadius: "12px",
          padding: "12px 16px",
          fontSize: "14px",
        },
      }}
    />
    <div className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">Environmental Screening Prototype</p>
          <h1>Environmental Screening for Construction Planning</h1>
          
          <p className="subtext">
            Submit project coordinates to screen for nearby Illinois endangered species and generate AI-assisted ecological planning context for highest occuring species.
          </p>
        </div>
      </header>

      <main className="layout">
        <section className="card">
          <h2>Project Input</h2>
          <form onSubmit={handleSubmit} className="form">
            <div className="mode-toggle">
              <button
                type="button"
                className={inputMode === "address" ? "active" : ""}
                onClick={() => setInputMode("address")}
              >
                Address
              </button>
              <button
                type="button"
                className={inputMode === "coordinates" ? "active" : ""}
                onClick={() => setInputMode("coordinates")}
              >
                Coordinates
              </button>
            </div>

              {inputMode === "address" ? (
              <>
                <label>Address</label>
                <input
                  name="address"
                  value={form.address}
                  onChange={updateField}
                  placeholder="123 Main St, Edwardsville, IL"
                />
                <button type="button" className="btn-secondary" onClick={handleAddressLookup} disabled={cooldowns.addressLookup > 0}>
                  {cooldowns.addressLookup > 0
                    ? `Try again in ${formatCooldown(cooldowns.addressLookup)}`
                    : "Find Address"}
                </button>

                {(form.lat && form.lon) && (
                  <div className="lookup-preview">
                    <small>Matched coordinates: {parseFloat(form.lat).toFixed(4)}, {parseFloat(form.lon).toFixed(4)}</small>
                  </div>
                )}
              </>
            ) : (
              <>
                <label>Latitude</label>
                <input
                  name="lat"
                  value={form.lat}
                  onChange={updateField}
                  placeholder="41.8781"
                />

                <label>Longitude</label>
                <input
                  name="lon"
                  value={form.lon}
                  onChange={updateField}
                  placeholder="-87.6298"
                />

                <button type="button" className="btn-secondary" onClick={handleCoordinateLookup} disabled={cooldowns.coordinateLookup > 0}>
                  {cooldowns.coordinateLookup > 0
                    ? `Try again in ${formatCooldown(cooldowns.coordinateLookup)}`
                    : "Find Address From Coordinates"}
                </button>

                {form.address && (
                  <div className="lookup-preview">
                    <small>Matched address: {form.address}</small>
                  </div>
                )}
              </>
            )}

            <label>
              Radius (miles)
              <input
                name="radius_miles"
                value={form.radius_miles}
                onChange={updateField}
                placeholder="7"
              />
            </label>

            <div ref={turnstileRef} className="captcha-container"></div>

            <button className="button" type="submit" disabled={loading || cooldowns.environmentScan > 0}>
              {cooldowns.environmentScan > 0
                ? `Try again in ${formatCooldown(cooldowns.environmentScan)}`
                : loading
                ? "Running Screen..."
                : "Run Environmental Screen"}
            </button>

            {/* {error.environmentScan && (
              <div className="error">
                {error.environmentScan}
              </div>
            )} */}
          </form>
          {/* {error && <p>{error}</p>}
          {loading && <p>{stepText}</p>} */}
          
          <div className="helper">
            <strong>Backend URL:</strong>{" "}
            {backendUrl || "Not set. Create .env from .env.example first."}
          </div>

          <div className="disclaimer">
            ⚠ This tool is intended ONLY as a preliminary environmental screening aid.
            Results are based on publicly available biodiversity observations through GBIF and AI
            analysis. They should NOT be considered authoritative regulatory guidance. Always consult 
            appropriate government agencies and environmental experts before beginning construction activities.
          </div>

        </section>

        <section className="card">
          

          {/* {Object.values(error).some(Boolean) && ( // Error above map display
            <div className="error">
              {error.general || error.addressLookup || error.coordinateLookup || error.environmentScan}
            </div>
          )} */}

          {loading && (
            <div className="loading-box">
              <div className="spinner"></div>
              <p>Processing environmental screening...</p>
            </div>
          )}

          { form.lat && form.lon && ( // !Object.values(error).some(Boolean) - Removes upon error
            <ScreeningMap
              lat={Number(form.lat)}
              lon={Number(form.lon)}
              radiusMiles={Number(form.radius_miles)}
              onPickLocation={async (lat, lon) => {
                resetResults();
                // 1. update coordinates immediately (fast UI response)
                setForm((prev) => ({
                  ...prev,
                  lat: lat.toFixed(6),
                  lon: lon.toFixed(6),
                }));

                try {
                  // 2. call your backend reverse geocode
                  const response = await fetch(
                    `${backendUrl}/geocode/reverse?lat=${lat}&lon=${lon}`
                  );

                  if (!response.ok) return;

                  const data = await response.json();

                  if (!data.best_match) return;

                  const best = data.best_match;

                  // 3. update address AFTER lookup completes
                  setForm((prev) => ({
                    ...prev,
                    lat: lat.toFixed(6),
                    lon: lon.toFixed(6),
                    address: best.label || prev.address,
                  }));
                } catch (err) {
                  // silent fail to not disrupt ux
                  console.error("Reverse geocode failed", err);
                }
              }}
            />
          
          )}

          {loading && (
            <div className="progress-box">
              <h3>Processing scan...</h3>
              <div className="progress-bar">
                <div
                  className="progress-bar-fill"
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
              <p className="progress-step-text">{stepText}</p>
            </div>
          )}

          {!Object.values(error).some(Boolean) && !loading && hasScanned && data?.gbif_hits?.length === 0 && (
            <div className="success-box">
              <div className="success-icon">✓</div>
              <div>
                <h3>No endangered species detected!</h3>
                <p>
                  No Illinois endangered species were identified within the selected
                  screening area based on the current GBIF query and filtering logic.
                </p>
              </div>
            </div>
          )}

          {!loading && data?.gbif_hits?.length > 0 && data && (
            <>
              <div className="summary">
                <div className="summary-box">
                  <span className="summary-label">Flagged species</span>
                  <span className="summary-value">{data.gbif_hits?.length ?? 0}</span>
                </div>
              </div>

              <div className="stack">
                {(data.gbif_hits || []).map((hit) => {
                  const context = (data.species_context || []).find(
                    (item) => item.scientific_name === hit.scientific_name
                  );

                  return (
                    <article className="species-card" key={hit.taxon_key}>
                      <div className="species-top">
                        <div>
                          <h3>{hit.scientific_name}</h3>
                          <p className="meta">
                            GBIF count: {hit.gbif_count} · Taxon key: {hit.taxon_key}
                          </p>
                        </div>
                        <span className="flag">Flagged</span>
                      </div>

                      <p className="analysis">
                        {context?.analysis ||
                          "No AI ecological context was returned for this species."}
                      </p>
                    </article>
                  );
                })}
              </div>
            </>
          )}
        </section>
      </main>
      <footer className="site-footer">
        <p>
          Data sources:{" "}
          <a href="https://www.gbif.org" target="_blank" rel="noreferrer">
            <img src={gbifLogo} alt="GBIF Logo" className="footer-logo" />
          </a>{"  "}
          {" "}
          <a
            href="https://naturalheritage.illinois.gov/dataresearch/access-our-data.html"
            target="_blank"
            rel="noreferrer"
          >
            <img src={inhsLogo} alt="Illinois Natural Heritage Logo" className="footer-logo" />
          </a>
          
        </p>

        <p>
          Map data ©{" "}
          <a
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noreferrer"
          >
            OpenStreetMap contributors
          </a>
          .
        </p>
        <p className="footer-note">
          This is a preliminary screening tool and does not replace official agency review,
          permitting, or provide environmental approval.
        </p>
        <a href="https://environmentscreen.onrender.com" target="_blank" rel="noreferrer">
          <img src={ourLogo} alt="Logo" width={128} height={128} className="our-logo"/>
        </a>
      </footer>
    </div>
    </>
  );
}

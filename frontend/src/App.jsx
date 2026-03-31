import { useMemo, useState, useRef, useEffect } from "react";
import { Toaster, toast } from "react-hot-toast";
import "leaflet/dist/leaflet.css";
import ScreeningMap from "./ScreeningMap";
import gbifLogo from "./assets/gbif-dot-org-green-logo.svg";
import inhsLogo from "./assets/dnr-nav-logo.png";
import ourLogo from "./assets/environment_screening_logo.png";
import openAILogo from "./assets/openailogo.png";
import mapTilerLogo from "./assets/mapTilerLogo.svg";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";
const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || "";

function SpeciesCard({ hit, context }) {
  const [thumb, setThumb] = useState(null);
  const wikiName = hit.scientific_name.replace(/ /g, "_");
  const wikiUrl = `https://en.wikipedia.org/wiki/${encodeURIComponent(wikiName)}`;

  useEffect(() => {
    let cancelled = false;
    fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(wikiName)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.thumbnail?.source) {
          setThumb(data.thumbnail.source);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [wikiName]);

  return (
    <article className="species-card">
      <div className="species-top">
        <div className="species-top-left">
          {thumb && (
            <a href={wikiUrl} target="_blank" rel="noreferrer noopener" className="species-thumb-link">
              <img src={thumb} alt={hit.scientific_name} className="species-thumb" />
            </a>
          )}
          <div className="species-names">
            {context?.common_name && <p className="common-name">{context.common_name}</p>}
            <h3>{hit.scientific_name}</h3>
            <a href={wikiUrl} target="_blank" rel="noreferrer noopener" className="wiki-link">
              Wikipedia ↗
            </a>
          </div>
        </div>
        <span className="flag">Flagged</span>
      </div>

      <div className="species-meta-row">
        <span className="species-meta-item">
          <span className="species-meta-label">GBIF observations</span>
          <span className="species-meta-value">{hit.gbif_count}</span>
        </span>
        <span className="species-meta-sep">·</span>
        <span className="species-meta-item">
          <span className="species-meta-label">Taxon key</span>
          <span className="species-meta-value">{hit.taxon_key}</span>
        </span>
      </div>
      

      {context?.tags?.length > 0 && (
        <div className="species-tags">
          {context.tags.map((tag) => (
            <span className="species-tag" key={tag}>{tag}</span>
          ))}
        </div>
      )}

      <div className="analysis-block">
        {context?.overview && (
          <div className="analysis-section">
            <p className="analysis-label">Overview</p>
            <p className="analysis">{context.overview}</p>
          </div>
        )}
        {context?.seasonal_concerns && (
          <div className="analysis-section">
            <p className="analysis-label">Seasonal Concerns</p>
            <p className="analysis">{context.seasonal_concerns}</p>
          </div>
        )}
        {context?.disruptive_activities && (
          <div className="analysis-section">
            <p className="analysis-label">Disruptive Activities</p>
            <p className="analysis">{context.disruptive_activities}</p>
          </div>
        )}
        {context?.recommendation && (
          <div className="analysis-section">
            <p className="analysis-label">Planning Recommendation</p>
            <p className="analysis">{context.recommendation}</p>
          </div>
        )}
        {!context?.overview && !context?.seasonal_concerns && !context?.disruptive_activities && !context?.recommendation && (
          <p className="analysis">No AI ecological context was returned for this species.</p>
        )}
      </div>
    </article>
  );
}

const initialForm = { // SIUE engineering building
  address: "Engineering Building, Southern Illinois University Edwardsville",
  lat: "38.792",
  lon: "-90.002",
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
  const [captchaToken, setCaptchaToken] = useState("");
  const [lookingUpAddress, setLookingUpAddress] = useState(false);
  const [lookingUpCoords, setLookingUpCoords] = useState(false);
  const [scanMeta, setScanMeta] = useState(null);
  const [finalizing, setFinalizing] = useState(false);

  const [notifications, setNotifications] = useState([]);

  const turnstileRef = useRef(null);
  const widgetIdRef = useRef(null);

  const backendUrl = useMemo(() => {
    if (!API_BASE_URL) return "";
    return API_BASE_URL.replace(/\/$/, "");
  }, []);


const pendingTokenResolveRef = useRef(null);
const pendingTokenRejectRef = useRef(null);

  useEffect(() => {
    if (!window.turnstile || !turnstileRef.current || !TURNSTILE_SITE_KEY) return;

    if (widgetIdRef.current !== null) return;

    widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
      sitekey: TURNSTILE_SITE_KEY,
      execution: "execute",
      appearance: "interaction-only",
      callback: (token) => {
        setCaptchaToken(token);

        if (pendingTokenResolveRef.current) {
          pendingTokenResolveRef.current(token);
          pendingTokenResolveRef.current = null;
          pendingTokenRejectRef.current = null;
        }
      },
      "expired-callback": () => {
        setCaptchaToken("");
      },
      "error-callback": () => {
        setCaptchaToken("");

        if (pendingTokenRejectRef.current) {
          pendingTokenRejectRef.current(
            new Error("Turnstile Verification failed.")
          );
          pendingTokenRejectRef.current = null;
          pendingTokenResolveRef.current = null;
        }
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
  setError((prev) => ({
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

async function getFreshTurnstileToken() {
  console.log("Getting fresh Turnstile token...");
  if (!window.turnstile || widgetIdRef.current === null) {
    throw new Error("Human verification widget is not ready yet. Please wait a moment and try again.");
  }

  const existing = window.turnstile.getResponse(widgetIdRef.current);

  if (existing) {
    console.log("Using existing Turnstile token...");
    return existing;
  }

  window.turnstile.reset(widgetIdRef.current);

  return await new Promise((resolve, reject) => {
    pendingTokenResolveRef.current = resolve;
    pendingTokenRejectRef.current = reject;
    window.turnstile.execute(widgetIdRef.current);
  });
}

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
    [action]: `${labels[action]} is rate limited. 
    Try again in ${formatCooldown(seconds)}`,
  }));

  setHasScanned(false);
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


      if (statusJson.status === "complete") {
        setProgress(100);
        clearInterval(interval);
        setFinalizing(true);

        // Stop the "Finalizing results" spinner 1s before results appear
        setTimeout(() => setFinalizing(false), 3000);

        setTimeout(() => {
          const isCached = statusJson.cached ?? false;
          const scannedAt = statusJson.result?.scanned_at ?? null;

          setData(statusJson.result);
          setScanMeta({ cached: isCached, scannedAt });
          setLoading(false);

          const timeStr = scannedAt
            ? new Date(scannedAt * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
            : null;

          if (isCached) {
            showToast(timeStr ? `Cached result · originally scanned at ${timeStr}` : "Cached result", "success");
          } else {
            showToast(timeStr ? `Live result · scanned at ${timeStr}` : "Scan complete", "success");
          }
        }, 4000);

        return;
      }

      if (statusJson.status === "error") {
        clearInterval(interval);
        setGeneralError("Scan failed.");
        setLoading(false);
        return;
      }
    } catch (err) {
      clearInterval(interval);
      setGeneralError("Polling failed.");
      setLoading(false);
    }
  }, 1000); // Poll every 1 second
}

const lastPickedRef = useRef(null);
async function handleAddressLookup() {
  setLookingUpAddress(true);
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
      lat: parseFloat(best.lat).toFixed(3),
      lon: parseFloat(best.lon).toFixed(3),
    }));
    resetResults();
    showToast(`Address found · ${parseFloat(best.lat).toFixed(3)}, ${parseFloat(best.lon).toFixed(3)}`, "success");
  } catch (err) {
    if (err.message !== "Rate limited") {
      setError((prev) => ({
        ...prev,
        addressLookup: err.message,
      }));
    }
  } finally {
    setLookingUpAddress(false);
  }
}

async function handleCoordinateLookup() {
  setLookingUpCoords(true);
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
      lat: parseFloat(best.lat).toFixed(3),
      lon: parseFloat(best.lon).toFixed(3),
    }));
    resetResults();
    showToast(`Address found · ${best.label}`, "success");
  } catch (err) {
    if (err.message !== "Rate limited") {
      setError((prev) => ({
        ...prev,
        coordinateLookup: err.message,
      }));
    }
  } finally {
    setLookingUpCoords(false);
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
  setScanMeta(null);
  setFinalizing(false);
}

function timeAgo(unixTimestamp) {
  const seconds = Math.floor(Date.now() / 1000 - unixTimestamp);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days !== 1 ? "s" : ""} ago`;
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
    lastToastRef.current = "";
    setError({ general: "", addressLookup: "", coordinateLookup: "", environmentScan: "" });
    setData({ gbif_hits: [], species_context: [] });
    setLoading(true);
    setProgress(0);

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
      const token = await getFreshTurnstileToken();
      console.log("Token obtained:", token ? "yes" : "no");

      if (!token) {
        throw new Error("Please complete CAPTCHA");
      }
      console.log("Starting scan start request");
      setHasScanned(true);
      const startResponse = await fetch(`${backendUrl}/scan/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          lat: Number(form.lat),
          lon: Number(form.lon),
          radius_miles: Number(form.radius_miles),
          captcha_token: token
        })
      });
      console.log("Scan start response status:", startResponse.status);

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

function downloadReport(scanData, meta, formValues) {
  const scanDate = meta?.scannedAt
    ? new Date(meta.scannedAt * 1000).toLocaleString()
    : new Date().toLocaleString();
  const cacheNote = meta?.cached ? " (cached result)" : "";
  const location = formValues.address || `${formValues.lat}, ${formValues.lon}`;

  const speciesRows = (scanData.gbif_hits || []).map((hit) => {
    const ctx = (scanData.species_context || []).find(
      (c) => c.scientific_name === hit.scientific_name
    );
    const tagPills = (ctx?.tags || []).map(
      (t) => `<span class="sp-tag">${t}</span>`
    ).join("");
    const sections = [
      { label: "Overview", key: "overview" },
      { label: "Seasonal Concerns", key: "seasonal_concerns" },
      { label: "Disruptive Activities", key: "disruptive_activities" },
      { label: "Planning Recommendation", key: "recommendation" },
    ].filter(({ key }) => ctx?.[key])
     .map(({ label, key }) => `
        <div class="sp-section">
          <div class="sp-context-label">${label}</div>
          <div class="sp-analysis">${ctx[key]}</div>
        </div>`).join("");
    return `
      <div class="sp">
        <div class="sp-header">
          <div>
            ${ctx?.common_name ? `<div class="sp-common">${ctx.common_name}</div>` : ""}
            <div class="sp-sci">${hit.scientific_name}</div>
          </div>
          <span class="sp-badge">Flagged</span>
        </div>
        <div class="sp-meta">
          GBIF observations: <strong>${hit.gbif_count}</strong>
          &nbsp;·&nbsp; Taxon key: <strong>${hit.taxon_key}</strong>
        </div>
        ${tagPills ? `<div class="sp-tags">${tagPills}</div>` : ""}
        ${sections || `<div class="sp-analysis">No ecological context available.</div>`}
      </div>`;
  }).join("");

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Environmental Screening Report</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #18322a; margin: 0; padding: 40px; font-size: 14px; }
    .header { border-bottom: 3px solid #2e7d32; padding-bottom: 16px; margin-bottom: 24px; }
    .header h1 { margin: 0 0 4px; font-size: 22px; color: #1a3d28; }
    .header p { margin: 2px 0; color: #557369; font-size: 13px; }
    .summary { display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }
    .stat { background: #f3faf4; border: 1px solid #d9e9dc; border-radius: 10px; padding: 12px 16px; min-width: 130px; }
    .stat-label { font-size: 11px; color: #557369; text-transform: uppercase; letter-spacing: 0.05em; }
    .stat-value { font-size: 22px; font-weight: 800; color: #214e36; }
    .stat.warn { background: #fffbeb; border: 2px solid #ffc107; }
    .stat.warn .stat-value { color: #b45309; }
    .sp { border: 1px solid #dce8de; border-radius: 12px; padding: 18px; margin-bottom: 16px; page-break-inside: avoid; }
    .sp-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
    .sp-common { font-size: 16px; font-weight: 700; color: #1a3d28; }
    .sp-sci { font-size: 13px; color: #557369; font-style: italic; margin-top: 2px; }
    .sp-badge { background: #fff4d8; color: #8d6400; border: 1px solid #efd38e; padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; white-space: nowrap; }
    .sp-meta { font-size: 12px; color: #6b7280; margin-bottom: 10px; }
    .sp-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
    .sp-tag { background: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9; padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 600; }
    .sp-section { margin-bottom: 10px; }
    .sp-context-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: #2e7d32; margin-bottom: 4px; }
    .sp-analysis { font-size: 13px; line-height: 1.7; color: #2b4a40; margin: 0; }
    .disclaimer { margin-top: 32px; padding: 12px 14px; font-size: 11px; color: #6b7280; background: #f5f5f5; border-left: 3px solid #c7c7c7; border-radius: 4px; line-height: 1.5; }
    @media print { body { padding: 24px; } }
  </style>
</head>
<body>
  <div class="header">
    <h1>Environmental Screening Report</h1>
    <p>Location: ${location}</p>
    <p>Coordinates: ${formValues.lat}, ${formValues.lon} &nbsp;·&nbsp; Radius: ${formValues.radius_miles} mi</p>
    <p>Scanned: ${scanDate}${cacheNote}</p>
  </div>

  <div class="summary">
    <div class="stat warn">
      <div class="stat-label">Flagged Species</div>
      <div class="stat-value">${scanData.gbif_hits?.length ?? 0}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Total Observed</div>
      <div class="stat-value">${scanData.found_species_count ?? 0}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Radius</div>
      <div class="stat-value">${scanData.input?.radius_miles ?? 0} mi</div>
    </div>
  </div>

  ${speciesRows}

  <div class="disclaimer">
    ⚠ This report is a preliminary environmental screening aid based on publicly available GBIF occurrence data and AI-generated ecological context.
    It is NOT authoritative regulatory guidance. Always consult qualified environmental professionals and relevant government agencies before making construction decisions.
  </div>
</body>
</html>`;

  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `environmental-screening-report-${new Date().toISOString().slice(0, 10)}.html`;
  a.click();
  URL.revokeObjectURL(url);
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
          padding: "20px 25px",
          width: "auto",
          maxWidth: "400px",
          lineHeight: "1.3",
          fontSize: "18px",
          boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
        },
      }}
    />
    <div className="page">
      <header className="hero">
        <div className="hero-inner">
          <div className="hero-text">
            <p className="eyebrow">Illinois Endangered Species · Construction Planning</p>
            <h1>Environmental Screening</h1>
            <p className="subtext">
              Screen a proposed construction site for nearby Illinois endangered species using GBIF occurrence data and AI-assisted ecological planning context.
            </p>
          </div>
          {/* <img src={ourLogo} alt="EnvironScreen" className="hero-logo" /> */}
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
                <button type="button" className="btn-secondary" onClick={handleAddressLookup} disabled={cooldowns.addressLookup > 0 || lookingUpAddress}>
                  {lookingUpAddress
                    ? "Looking up..."
                    : cooldowns.addressLookup > 0
                    ? `Try again in ${formatCooldown(cooldowns.addressLookup)}`
                    : "Find Address"}
                </button>

                {(form.lat && form.lon) && (
                  <div className="lookup-preview">
                    <small>Matched coordinates: {parseFloat(form.lat).toFixed(3)}, {parseFloat(form.lon).toFixed(3)}</small>
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

                <button type="button" className="btn-secondary" onClick={handleCoordinateLookup} disabled={cooldowns.coordinateLookup > 0 || lookingUpCoords}>
                  {lookingUpCoords
                    ? "Looking up..."
                    : cooldowns.coordinateLookup > 0
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

            <button className="button" type="submit" disabled={loading || cooldowns.environmentScan > 0}>
              {cooldowns.environmentScan > 0
                ? `Try again in ${formatCooldown(cooldowns.environmentScan)}`
                : loading
                ? "Running Screen..."
                : "Run Environmental Screen"}
            </button>

            <div ref={turnstileRef} className="captcha-container"></div>

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

          { form.lat && form.lon && ( // !Object.values(error).some(Boolean) - Removes upon error
            <ScreeningMap
              lat={Number(form.lat)}
              lon={Number(form.lon)}
              radiusMiles={Number(form.radius_miles)}


              onPickLocation={async (lat, lon) => {
                const roundedLat = Number(lat.toFixed(3));
                const roundedLon = Number(lon.toFixed(3));

                const newKey = `${roundedLat},${roundedLon}`;

                if (lastPickedRef.current === newKey) {
                  // If the rounded coordinates are the same as current, do nothing
                  return;
                }
                lastPickedRef.current = newKey;

                resetResults();
                
                setForm((prev) => ({
                  ...prev,
                  lat: roundedLat,
                  lon: roundedLon,
                }));

                try {
                  // 2. call your backend reverse geocode
                  const response = await fetch(
                    `${backendUrl}/geocode/reverse?lat=${roundedLat}&lon=${roundedLon}`
                  );

                  if (!response.ok) return;

                  const data = await response.json();

                  if (!data.best_match) return;

                  const best = data.best_match;

                  // 3. update address AFTER lookup completes
                  setForm((prev) => ({
                    ...prev,
                    lat: roundedLat,
                    lon: roundedLon,
                    address: best.label || prev.address,
                  }));
                } catch (err) {
                  // silent fail to not disrupt ux
                  console.error("Reverse geocode failed", err);
                }
              }}
            />
          
          )}

          {loading && (() => {
            const SCAN_STEPS = [
              { label: "Validating Human", threshold: 1 },
              { label: "Loading taxon lookup", threshold: 10 },
              { label: "Querying GBIF species", threshold: 35 },
              { label: "Cross-referencing endangered species", threshold: 60 },
              { label: "Generating AI ecological context", threshold: 86 },
              { label: "Finalizing results", threshold: 100 },
            ];
            return (
              <div className="progress-box">
                <h3>Processing scan...</h3>
                <div className="progress-bar">
                  <div
                    className="progress-bar-fill"
                    style={{ width: `${progress}%` }}
                  ></div>
                </div>
                <ol className="scan-steps">
                  {SCAN_STEPS.map((step) => {
                    const isLastStep = step.threshold === 100;
                    const done = isLastStep
                      ? progress >= step.threshold && !finalizing
                      : progress >= step.threshold;
                    const active = isLastStep
                      ? finalizing
                      : !done && SCAN_STEPS.find((s) => progress < s.threshold) === step;
                    return (
                      <li
                        key={step.label}
                        className={`scan-step ${done ? "scan-step-done" : active ? "scan-step-active" : "scan-step-pending"}`}
                      >
                        <span className="scan-step-circle">
                          {done ? "✓" : active ? <span className="scan-step-spinner" /> : ""}
                        </span>
                        <span className="scan-step-label">{step.label}</span>
                      </li>
                    );
                  })}
                </ol>
              </div>
            );
          })()}

          {!hasScanned && !loading && (
            <div className="skeleton-placeholder">
              <div className="skeleton-summary-row">
                <div className="skeleton"></div>
                <div className="skeleton"></div>
                <div className="skeleton"></div>
              </div>
              <div className="skeleton-stack">
                <div className="skeleton skeleton-card"></div>
                <div className="skeleton skeleton-card"></div>
              </div>
            </div>
          )}

          {loading && (
            <div className="skeleton-placeholder loading">
              <div className="skeleton-summary-row">
                <div className="skeleton"></div>
                <div className="skeleton"></div>
                <div className="skeleton"></div>
              </div>
              <div className="skeleton-stack">
                <div className="skeleton skeleton-card"></div>
                <div className="skeleton skeleton-card"></div>
              </div>
            </div>
          )}

          {!Object.values(error).some(Boolean) && !loading && hasScanned && data?.gbif_hits?.length === 0 && (
            <div className="success-box">
              <div className="success-icon">✓</div>
              <div>
                <h3>No endangered species detected!</h3>
                <p>
                  No Illinois endangered species were identified, from 2015-2026, within the
                  selected screening area based on the current GBIF query and filtering logic.
                </p>
              </div>
            </div>
          )}

            

          {!loading && data && hasScanned && (
            <>
              <div className="summary">
                <div className="summary-box warning">
                  <span className="summary-label" color="yellow">Flagged species</span>
                  <span className="summary-value">{data.gbif_hits?.length ?? 0}</span>
                </div>
                <div className="summary-box">
                  <span className="summary-label">Total Species Observed</span>
                  <span className="summary-value">
                    {data.found_species_count ?? 0}
                  </span>
                </div>
                <div className="summary-box">
                  <span className="summary-label">Radius</span>
                  <span className="summary-value">
                    {data.input?.radius_miles ?? 0} mi
                  </span>
                </div>
              </div>

              {data.gbif_hits?.length > 0 && (
                <button
                  type="button"
                  className="btn-download"
                  onClick={() => downloadReport(data, scanMeta, form)}
                >
                  Download Screening Report
                </button>
              )}

              <div className="stack">
                {(data.gbif_hits || []).map((hit) => {
                  const context = (data.species_context || []).find(
                    (item) => item.scientific_name === hit.scientific_name
                  );

                  return <SpeciesCard key={hit.taxon_key} hit={hit} context={context} />;
                })}
              </div>
            </>
          )}
        </section>
      </main>
      <footer className="site-footer">
        <div className="footer-inner">
          <div className="footer-sources">
            <span className="footer-sources-label">Powered by</span>
            <a href="https://www.gbif.org" target="_blank" rel="noreferrer" className="footer-source-link">
              <img src={gbifLogo} alt="GBIF" className="footer-logo" />
            </a>
            <a href="https://naturalheritage.illinois.gov/dataresearch/access-our-data.html" target="_blank" rel="noreferrer" className="footer-source-link">
              <img src={inhsLogo} alt="Illinois Natural Heritage Survey" className="footer-logo footer-logo-inhs" />
            </a>
            <a href="https://www.maptiler.com" target="_blank" rel="noreferrer" className="footer-source-link footer-text-source">
              <img src={mapTilerLogo} alt="MapTiler" className="footer-logo footer-logo-maptiler" />
            </a>
            <a href="https://openai.com" target="_blank" rel="noreferrer" className="footer-source-link footer-text-source">
              <img src={openAILogo} alt="OpenAI" className="footer-logo footer-logo-openai" />
            </a>
          </div>
          <p className="footer-map-credit">
            Map tiles ©{" "}
            <a href="https://www.maptiler.com/copyright/" target="_blank" rel="noreferrer">MapTiler</a>
            {" · "}Data ©{" "}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>
          </p>
          <p className="footer-note">
            Preliminary screening only — does not replace official agency review, permitting, or regulatory approval.
          </p>
        </div>
      </footer>
    </div>
    </>
  );
}

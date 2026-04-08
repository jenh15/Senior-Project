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
    <div className="species-report">
      <div className="report-header">
        <div className="species-identity">
          {thumb && (
            <a href={wikiUrl} target="_blank" rel="noreferrer noopener" className="species-thumb-link">
              <img src={thumb} alt={hit.scientific_name} className="species-thumb" />
            </a>
          )}
          <div className="species-names">
            {context?.common_name && <p className="species-common">{context.common_name}</p>}
            <p className="species-scientific">{hit.scientific_name}</p>
            <a href={wikiUrl} target="_blank" rel="noreferrer noopener" className="wiki-link">
              Wikipedia ↗
            </a>
          </div>
        </div>
        <span className="flagged-chip">Flagged</span>
      </div>

      <div className="species-meta">
        <div className="meta-item">
          <span className="meta-label">GBIF Observations</span>
          <span className="meta-value">{hit.gbif_count}</span>
        </div>
        <div className="meta-divider" />
        <div className="meta-item">
          <span className="meta-label">Taxon Key</span>
          <span className="meta-value">{hit.taxon_key}</span>
        </div>
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
            <p className="analysis-text">{context.overview}</p>
          </div>
        )}
        {context?.seasonal_concerns && (
          <div className="analysis-section">
            <p className="analysis-label">Seasonal Concerns</p>
            <p className="analysis-text">{context.seasonal_concerns}</p>
          </div>
        )}
        {context?.disruptive_activities && (
          <div className="analysis-section">
            <p className="analysis-label">Disruptive Activities</p>
            <p className="analysis-text">{context.disruptive_activities}</p>
          </div>
        )}
        {context?.recommendation && (
          <div className="analysis-section">
            <p className="analysis-label">Planning Recommendation</p>
            <p className="analysis-text">{context.recommendation}</p>
          </div>
        )}
        {!context?.overview && !context?.seasonal_concerns && !context?.disruptive_activities && !context?.recommendation && (
          <p className="analysis-missing">No ecological context was returned for this species.</p>
        )}
      </div>
    </div>
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
        <div class="sp-inner">
          <div class="sp-header">
            <div>
              ${ctx?.common_name ? `<div class="sp-common">${ctx.common_name}</div>` : ""}
              <div class="sp-sci">${hit.scientific_name}</div>
            </div>
            <span class="sp-badge">Flagged</span>
          </div>
          <div class="sp-meta">
            <span>GBIF Observations</span><strong>${hit.gbif_count}</strong>
            <div class="sp-meta-divider"></div>
            <span>Taxon Key</span><strong>${hit.taxon_key}</strong>
          </div>
          ${tagPills ? `<div class="sp-tags">${tagPills}</div>` : ""}
          ${sections || `<div class="sp-analysis">No ecological context available.</div>`}
        </div>
      </div>`;
  }).join("");

  const html = `<!DOCTYPE html>
      <html lang="en">
      <head>
        <meta charset="UTF-8"/>
        <title>Environmental Screening Report</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        <style>
          *, *::before, *::after { box-sizing: border-box; }
          body {
            font-family: 'Figtree', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #EDEBE4;
            color: #1B1916;
            margin: 0;
            padding: 40px;
            font-size: 14px;
            line-height: 1.6;
          }
          .page { max-width: 860px; margin: 0 auto; }

          /* Header */
          .header {
            background: #1A3C29;
            color: #fff;
            border-radius: 12px;
            padding: 24px 28px;
            margin-bottom: 24px;
          }
          .header-eyebrow {
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: #A8C8B4;
            margin-bottom: 6px;
          }
          .header h1 { margin: 0 0 12px; font-size: 22px; font-weight: 800; color: #fff; }
          .header-meta { display: flex; flex-wrap: wrap; gap: 6px 20px; font-size: 12px; color: #CCE2D6; }
          .header-meta strong { color: #fff; font-weight: 600; }

          /* Summary stats */
          .summary { display: flex; gap: 12px; margin-bottom: 28px; flex-wrap: wrap; }
          .stat {
            background: #fff;
            border: 1px solid #D0CBC1;
            border-radius: 10px;
            padding: 14px 18px;
            min-width: 140px;
          }
          .stat-label {
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #8C887F;
            margin-bottom: 4px;
          }
          .stat-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 24px;
            font-weight: 700;
            color: #1B1916;
          }
          .stat.warn { background: #FEF9F2; border-color: #F0D0A0; border-width: 1px; }
          .stat.warn .stat-value { color: #9E5010; }
          .stat.warn .stat-label { color: #C06B18; }

          /* Species cards */
          .sp {
            background: #fff;
            border: 1px solid #D0CBC1;
            border-radius: 10px;
            margin-bottom: 14px;
            overflow: hidden;
            page-break-inside: avoid;
            position: relative;
          }
          .sp::before {
            content: '';
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 3px;
            background: #D9914D;
            border-radius: 10px 0 0 10px;
          }
          .sp-inner { padding: 16px 18px 16px 22px; }
          .sp-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; gap: 12px; }
          .sp-common { font-size: 15px; font-weight: 700; color: #1B1916; }
          .sp-sci { font-size: 12px; color: #5A5650; font-style: italic; margin-top: 2px; }
          .sp-badge {
            background: #FBF0DC;
            color: #9E5010;
            border: 1px solid #F0D0A0;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            white-space: nowrap;
            flex-shrink: 0;
          }
          .sp-meta {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            background: #F6F4EF;
            border: 1px solid #E2DDD6;
            border-radius: 6px;
            padding: 6px 10px;
            margin-bottom: 10px;
            font-size: 11px;
            color: #5A5650;
          }
          .sp-meta strong {
            font-family: 'JetBrains Mono', monospace;
            font-weight: 500;
            color: #1B1916;
          }
          .sp-meta-divider { width: 1px; height: 16px; background: #D0CBC1; }
          .sp-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 12px; }
          .sp-tag {
            background: #EBF5EF;
            color: #235436;
            border: 1px solid #CCE2D6;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.04em;
          }
          .sp-section { margin-bottom: 10px; }
          .sp-context-label {
            font-size: 9px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: #235436;
            margin-bottom: 4px;
          }
          .sp-analysis { font-size: 13px; line-height: 1.7; color: #3E3B34; margin: 0; }

          /* Disclaimer */
          .disclaimer {
            margin-top: 28px;
            padding: 12px 16px;
            font-size: 11px;
            color: #5A5650;
            background: #FEF9F2;
            border: 1px solid #F0D0A0;
            border-left: 3px solid #D9914D;
            border-radius: 6px;
            line-height: 1.6;
          }

          @media print {
            body { background: #fff; padding: 24px; }
            .header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
          }
        </style>
      </head>
      <body>
      <div class="page">
        <div class="header">
          <div class="header-eyebrow">Illinois · Preliminary Screening · EcoRisk AI</div>
          <h1>Environmental Screening Report</h1>
          <div class="header-meta">
            <span><strong>Location:</strong> ${location}</span>
            <span><strong>Coordinates:</strong> ${formValues.lat}, ${formValues.lon}</span>
            <span><strong>Radius:</strong> ${formValues.radius_miles} mi</span>
            <span><strong>Scanned:</strong> ${scanDate}${cacheNote}</span>
          </div>
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
            <div class="stat-label">Search Radius</div>
            <div class="stat-value">${scanData.input?.radius_miles ?? 0} mi</div>
          </div>
        </div>

        ${speciesRows}

        <div class="disclaimer">
          ⚠ This report is a preliminary environmental screening aid based on publicly available GBIF occurrence data and AI-generated ecological context.
          It is NOT authoritative regulatory guidance. Always consult qualified environmental professionals and relevant government agencies before making construction decisions.
        </div>
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
            fontFamily: "'Figtree', system-ui, sans-serif",
            borderRadius: "6px",
            padding: "12px 16px",
            fontSize: "13px",
            fontWeight: "500",
            boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
          },
        }}
      />

      <div className="app-shell">

        {/* Topbar */}
        <header className="topbar">
          <div className="topbar-inner">
            <div className="topbar-brand">
              <div className="topbar-mark">
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                  <rect width="10" height="10" rx="1.5" fill="rgba(255,255,255,0.65)" />
                </svg>
              </div>
              <span className="topbar-name">EcoRisk AI</span>
              <div className="topbar-sep" />
              <span className="topbar-subtitle">Illinois Endangered Species · Construction Pre-Screen</span>
            </div>
            <span className="topbar-pill">Preliminary Screening</span>
          </div>
        </header>

        {/* Workspace */}
        <main className="workspace">

          {/* Left: Site Parameters */}
          <aside className="panel panel-params">
            <div className="panel-header">
              <span className="panel-label">Site Parameters</span>
            </div>

            <form onSubmit={handleSubmit} className="params-form">

              <div className="mode-selector">
                <button
                  type="button"
                  className={`mode-btn${inputMode === "address" ? " active" : ""}`}
                  onClick={() => setInputMode("address")}
                >
                  Address
                </button>
                <button
                  type="button"
                  className={`mode-btn${inputMode === "coordinates" ? " active" : ""}`}
                  onClick={() => setInputMode("coordinates")}
                >
                  Coordinates
                </button>
              </div>

              {inputMode === "address" ? (
                <div className="field-group">
                  <div className="field">
                    <label className="field-label">Street Address</label>
                    <input
                      className="field-input"
                      name="address"
                      value={form.address}
                      onChange={updateField}
                      placeholder="123 Main St, Chicago, IL"
                    />
                  </div>
                  <button
                    type="button"
                    className="btn-resolve"
                    onClick={handleAddressLookup}
                    disabled={cooldowns.addressLookup > 0 || lookingUpAddress}
                  >
                    {lookingUpAddress
                      ? "Locating..."
                      : cooldowns.addressLookup > 0
                      ? `Wait ${formatCooldown(cooldowns.addressLookup)}`
                      : "Resolve Address"}
                  </button>
                  {form.lat && form.lon && (
                    <p className="coord-preview">
                      {parseFloat(form.lat).toFixed(3)}&deg; N &nbsp;&middot;&nbsp; {parseFloat(form.lon).toFixed(3)}&deg; W
                    </p>
                  )}
                </div>
              ) : (
                <div className="field-group">
                  <div className="field-pair">
                    <div className="field">
                      <label className="field-label">Latitude</label>
                      <input
                        className="field-input field-input--mono"
                        name="lat"
                        value={form.lat}
                        onChange={updateField}
                        placeholder="41.878"
                      />
                    </div>
                    <div className="field">
                      <label className="field-label">Longitude</label>
                      <input
                        className="field-input field-input--mono"
                        name="lon"
                        value={form.lon}
                        onChange={updateField}
                        placeholder="-87.629"
                      />
                    </div>
                  </div>
                  <button
                    type="button"
                    className="btn-resolve"
                    onClick={handleCoordinateLookup}
                    disabled={cooldowns.coordinateLookup > 0 || lookingUpCoords}
                  >
                    {lookingUpCoords
                      ? "Resolving..."
                      : cooldowns.coordinateLookup > 0
                      ? `Wait ${formatCooldown(cooldowns.coordinateLookup)}`
                      : "Resolve Coordinates"}
                  </button>
                  {form.address && (
                    <p className="coord-preview">{form.address}</p>
                  )}
                </div>
              )}

              <div className="field">
                <div className="radius-label-row">
                  <label className="field-label">Search Radius</label>
                  <span className="radius-value">{form.radius_miles} mi</span>
                </div>
                <input
                  className="radius-slider"
                  type="range"
                  name="radius_miles"
                  min="0"
                  max="50"
                  step="1"
                  value={form.radius_miles}
                  onChange={updateField}
                />
              </div>

              <button
                className="btn-primary"
                type="submit"
                disabled={loading || cooldowns.environmentScan > 0}
              >
                {cooldowns.environmentScan > 0
                  ? `Rate limited · ${formatCooldown(cooldowns.environmentScan)}`
                  : loading
                  ? "Running Screen..."
                  : "Run Environmental Screen"}
              </button>

              <div ref={turnstileRef} className="captcha-container" />
            </form>

            <div className="panel-footer">
              <p className="disclaimer-text">
                ⚠ Preliminary screening only. Results are based on publicly available GBIF occurrence
                data and AI analysis — not authoritative regulatory guidance. Verify with qualified
                environmental professionals before construction.
              </p>
              <div className="backend-row">
                <span
                  className="status-dot"
                  style={{ background: backendUrl ? "var(--forest-3)" : "var(--red)" }}
                />
                <span className="status-text">
                  {backendUrl || "API not configured — set VITE_API_BASE_URL"}
                </span>
              </div>
            </div>
          </aside>

          {/* Right: Map + Results */}
          <section className="panel panel-results">

            {form.lat && form.lon && (
              <div className="map-section">
                <div className="map-label-row">
                  <span className="section-label">Project Site</span>
                  {scanMeta && (
                    <span className={`cache-chip ${scanMeta.cached ? "cache-chip--cached" : "cache-chip--live"}`}>
                      {scanMeta.cached ? "Cached" : "Live"}
                      {scanMeta.scannedAt
                        ? ` · ${new Date(scanMeta.scannedAt * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                        : ""}
                    </span>
                  )}
                </div>
                <ScreeningMap
                  lat={Number(form.lat)}
                  lon={Number(form.lon)}
                  radiusMiles={Number(form.radius_miles)}
                  onPickLocation={async (lat, lon) => {
                    const roundedLat = Number(lat.toFixed(3));
                    const roundedLon = Number(lon.toFixed(3));
                    const newKey = `${roundedLat},${roundedLon}`;
                    if (lastPickedRef.current === newKey) return;
                    lastPickedRef.current = newKey;
                    resetResults();
                    setForm((prev) => ({ ...prev, lat: roundedLat, lon: roundedLon }));
                    try {
                      const response = await fetch(`${backendUrl}/geocode/reverse?lat=${roundedLat}&lon=${roundedLon}`);
                      if (!response.ok) return;
                      const data = await response.json();
                      if (!data.best_match) return;
                      const best = data.best_match;
                      setForm((prev) => ({ ...prev, lat: roundedLat, lon: roundedLon, address: best.label || prev.address }));
                    } catch (err) {
                      console.error("Reverse geocode failed", err);
                    }
                  }}
                />
              </div>
            )}

            {loading && (() => {
              const SCAN_STEPS = [
                { label: "Validating Human",                  threshold: 1   },
                { label: "Loading taxon lookup",              threshold: 10  },
                { label: "Querying GBIF species",             threshold: 35  },
                { label: "Cross-referencing endangered list", threshold: 60  },
                { label: "Generating AI ecological context",  threshold: 86  },
                { label: "Finalizing results",                threshold: 100 },
              ];
              return (
                <div className="scan-monitor">
                  <div className="monitor-head">
                    <span className="monitor-title">Processing Scan</span>
                    <span className="monitor-pct">{progress}%</span>
                  </div>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${progress}%` }} />
                  </div>
                  <div className="pipeline">
                    {SCAN_STEPS.map((step) => {
                      const isLastStep = step.threshold === 100;
                      const done = isLastStep
                        ? progress >= step.threshold && !finalizing
                        : progress >= step.threshold;
                      const active = isLastStep
                        ? finalizing
                        : !done && SCAN_STEPS.find((s) => progress < s.threshold) === step;
                      return (
                        <div
                          key={step.label}
                          className={`pipeline-step ${done ? "step-done" : active ? "step-active" : "step-pending"}`}
                        >
                          <div className="step-node">{done ? "✓" : ""}</div>
                          <span className="step-text">{step.label}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}

            {!hasScanned && !loading && (
              <div className="skeleton-screen">
                <div className="skeleton-stats">
                  <div className="skel skel-stat" />
                  <div className="skel skel-stat" />
                  <div className="skel skel-stat" />
                </div>
                <div className="skel skel-card" />
                <div className="skel skel-card" />
              </div>
            )}

            {loading && (
              <div className="skeleton-screen loading">
                <div className="skeleton-stats">
                  <div className="skel skel-stat" />
                  <div className="skel skel-stat" />
                  <div className="skel skel-stat" />
                </div>
                <div className="skel skel-card" />
                <div className="skel skel-card" />
              </div>
            )}

            {!loading && hasScanned && !Object.values(error).some(Boolean) && data?.gbif_hits?.length === 0 && (
              <div className="result-clear">
                <div className="clear-icon">✓</div>
                <div>
                  <p className="clear-title">No Endangered Species Detected</p>
                  <p className="clear-text">
                    No Illinois-listed endangered species were identified within the selected
                    screening area based on current GBIF occurrence data (2015–2026).
                  </p>
                </div>
              </div>
            )}

            {!loading && hasScanned && data && (
              <>
                <div className="results-bar">
                  <div className="stats-row">
                    <div className="stat-item stat-item--warn">
                      <span className="stat-label">Flagged Species</span>
                      <span className="stat-value">{data.gbif_hits?.length ?? 0}</span>
                    </div>
                    <div className="stat-divider" />
                    <div className="stat-item">
                      <span className="stat-label">Total Observed</span>
                      <span className="stat-value">{data.found_species_count ?? 0}</span>
                    </div>
                    <div className="stat-divider" />
                    <div className="stat-item">
                      <span className="stat-label">Radius</span>
                      <span className="stat-value">{data.input?.radius_miles ?? 0} mi</span>
                    </div>
                  </div>
                  {data.gbif_hits?.length > 0 && (
                    <button
                      type="button"
                      className="btn-report"
                      onClick={() => downloadReport(data, scanMeta, form)}
                    >
                      ↓ Download Report
                    </button>
                  )}
                </div>

                <div className="species-list">
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
              <span className="footer-source-label">Powered by</span>
              <a href="https://www.gbif.org" target="_blank" rel="noreferrer" className="footer-logo-link">
                <img src={gbifLogo} alt="GBIF" className="footer-logo" />
              </a>
              <a href="https://naturalheritage.illinois.gov/dataresearch/access-our-data.html" target="_blank" rel="noreferrer" className="footer-logo-link">
                <img src={inhsLogo} alt="Illinois Natural Heritage Survey" className="footer-logo footer-logo--inhs" />
              </a>
              <a href="https://www.maptiler.com" target="_blank" rel="noreferrer" className="footer-logo-link">
                <img src={mapTilerLogo} alt="MapTiler" className="footer-logo footer-logo--maptiler" />
              </a>
              <a href="https://openai.com" target="_blank" rel="noreferrer" className="footer-logo-link">
                <img src={openAILogo} alt="OpenAI" className="footer-logo footer-logo--openai" />
              </a>
            </div>
            <p className="footer-attribution">
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

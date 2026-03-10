import { useMemo, useState } from "react";
import gbifLogo from "./assets/gbif-dot-org-green-logo.svg";
import inhsLogo from "./assets/dnr-nav-logo.jpeg";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

const initialForm = {
  lat: "38.792170",
  lon: "-90.001636",
  radius_miles: "2"
};

export default function App() {
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasScanned, setHasScanned] = useState(false);
  const [data, setData] = useState({
    gbif_hits: [],
    species_context: []
  });
  const [jobId, setJobId] = useState(null); 
  const [progress, setProgress] = useState(0);
  const [stepText, setStepText] = useState("");

  const backendUrl = useMemo(() => {
    if (!API_BASE_URL) return "";
    return API_BASE_URL.replace(/\/$/, "");
  }, []);

  function updateField(event) {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  const validateInputs = () => {
  const lat = parseFloat(form.lat);
  const lon = parseFloat(form.lon);

  if (isNaN(lat) || isNaN(lon)) {
    setError("Latitude and longitude must be numeric");
    return false;
  }

  if (lat < -90 || lat > 90) {
    setError("Latitude must be between -90 and 90");
    return false;
  }

  if (lon < -180 || lon > 180) {
    setError("Longitude must be between -180 and 180");
    return false;
  }

  if (isNaN(parseFloat(form.radius_miles)) || parseFloat(form.radius_miles) < 0 || parseFloat(form.radius_miles) > 100) {
    setError("Radius must be a positive number and less than 100 miles");
    return false;
  }

  return true;
};

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
      }

      if (statusJson.status === "error") {
        clearInterval(interval);
        setError(statusJson.error || "Scan failed.");
        setLoading(false);
      }
    } catch (err) {
      clearInterval(interval);
      setError(err.message || "Polling failed.");
      setLoading(false);
    }
  }, 1000);
}


  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setData({ gbif_hits: [], species_context: [] });
    setLoading(true);
    setHasScanned(true);
    setProgress(0);
    setStepText("Starting scan...");

    try {
      if (!backendUrl) {
        throw new Error("Missing VITE_API_BASE_URL. Add it to a .env file.");
      }
      if (!validateInputs()) {
        setLoading(false);
        return;
      }
      const startResponse = await fetch(`${backendUrl}/scan/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          lat: Number(form.lat),
          lon: Number(form.lon),
          radius_miles: Number(form.radius_miles)
        })
      });

      if (!startResponse.ok) {
        const text = await startResponse.text();
        throw new Error(text || "Failed to start scan.");
      }

      const startJson = await startResponse.json();
      const newJobID = startJson.job_id;

      if (!newJobID) {
        throw new Error("Backend did not return a job ID");
      }

      setJobId(newJobID);
      // Polling loop
      pollScanStatus(newJobID);

    } catch (err) {
      setError(err.message || "Something went wrong.");
      setLoading(false);
    }
  }

  return (
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
            <label>
              Latitude
              <input
                name="lat"
                value={form.lat}
                onChange={updateField}
                placeholder="41.8781"
              />
            </label>

            <label>
              Longitude
              <input
                name="lon"
                value={form.lon}
                onChange={updateField}
                placeholder="-87.6298"
              />
            </label>

            <label>
              Radius (miles)
              <input
                name="radius_miles"
                value={form.radius_miles}
                onChange={updateField}
                placeholder="7"
              />
            </label>

            <button className="button" type="submit" disabled={loading}>
              {loading ? "Running Screen..." : "Run Environmental Screen"}
            </button>
          </form>

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
          <h2>Results</h2>

          {error && <div className="error">{error}</div>}

          {loading && (
            <div className="loading-box">
              <div className="spinner"></div>
              <p>Processing environmental screening...</p>
            </div>
          )}

          {!error && form.lat && form.lon && (
          <iframe
            width="100%"
            height="300"
            style={{ border: 0, borderRadius: "12px" }}
            src={`https://www.openstreetmap.org/export/embed.html?bbox=${
              form.lon - 0.05
            },${form.lat - 0.05},${Number(form.lon) + 0.05},${Number(form.lat) + 0.05}&marker=${form.lat},${form.lon}`}
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


          {!loading && !error && !data && (
            <div className="empty">
              No results yet. Enter coordinates and run the screening workflow.
            </div>
          )}

          {!error && !loading && hasScanned && data?.gbif_hits?.length === 0 && (
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
          <img src="../public/environment_screening_logo.png" alt="Logo" width={128} height={128} className="our-logo"/>
        </a>
      </footer>
    </div>
  );
}

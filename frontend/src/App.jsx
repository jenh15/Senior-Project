import { useMemo, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

const initialForm = {
  lat: "38.617110",
  lon: "-90.207191",
  radius_miles: "2"
};

export default function App() {
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState({
    gbif_hits: [],
    species_context: []
  });

  const backendUrl = useMemo(() => {
    if (!API_BASE_URL) return "";
    return API_BASE_URL.replace(/\/$/, "");
  }, []);

  function updateField(event) {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setData(null);
    setLoading(true);

    try {
      if (!backendUrl) {
        throw new Error("Missing VITE_API_BASE_URL. Add it to a .env file.");
      }

      const response = await fetch(`${backendUrl}/scan`, {
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

      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || "Request failed.");
      }

      const json = await response.json();
      setData(json);
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
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
            Submit project coordinates to screen for nearby Illinois endangered species and receive AI-assisted ecological planning context.
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

            <button type="submit" disabled={loading}>
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


          {!loading && !error && !data && (
            <div className="empty">
              No results yet. Enter coordinates and run the screening workflow.
            </div>
          )}

          {!loading && data && data?.gbif_hits?.length === 0 && (
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
    </div>
  );
}

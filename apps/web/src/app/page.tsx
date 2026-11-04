const capabilities = [
  {
    title: "Learning materials",
    description: "Upload and organize school-approved PDFs, documents, presentations and scanned notes.",
    status: "Foundation",
  },
  {
    title: "Evidence-grounded questions",
    description: "Generate question drafts from selected source passages, with page-level references.",
    status: "Planned",
  },
  {
    title: "Visual assessments",
    description: "Create editable diagrams, labelled illustrations and data-driven graphs.",
    status: "Planned",
  },
  {
    title: "Online and offline exams",
    description: "Deliver timed examinations with autosave, local persistence and synchronization.",
    status: "Planned",
  },
];

export default function HomePage() {
  return (
    <main style={{ maxWidth: 1120, margin: "0 auto", padding: "64px 24px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 48 }}>
        <div
          aria-hidden="true"
          style={{
            width: 38,
            height: 38,
            borderRadius: 11,
            background: "#2457d6",
            color: "white",
            display: "grid",
            placeItems: "center",
            fontWeight: 800,
          }}
        >
          C
        </div>
        <strong>Intelligent CBT</strong>
        <span style={{ color: "#667085", fontSize: 13 }}>Platform foundation</span>
      </div>

      <section style={{ maxWidth: 760, marginBottom: 44 }}>
        <p style={{ color: "#2457d6", fontWeight: 700, letterSpacing: 1.2, fontSize: 12 }}>
          SCHOOL-CONTROLLED ASSESSMENT
        </p>
        <h1 style={{ fontSize: "clamp(36px, 6vw, 58px)", lineHeight: 1.08, margin: "12px 0 18px" }}>
          Examinations built from your school&apos;s learning materials.
        </h1>
        <p style={{ color: "#667085", fontSize: 18, lineHeight: 1.7 }}>
          One platform for web and Windows desktop. Teachers stay in control:
          AI-generated questions must be supported by approved school content
          and reviewed before an examination is published.
        </p>
      </section>

      <section
        aria-label="Platform capabilities"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
          gap: 16,
        }}
      >
        {capabilities.map((item) => (
          <article
            key={item.title}
            style={{
              background: "#fff",
              border: "1px solid #e4e7ec",
              borderRadius: 16,
              padding: 22,
            }}
          >
            <p style={{ color: "#2457d6", fontSize: 12, fontWeight: 700 }}>{item.status}</p>
            <h2 style={{ fontSize: 18, margin: "8px 0" }}>{item.title}</h2>
            <p style={{ color: "#667085", lineHeight: 1.6, margin: 0 }}>{item.description}</p>
          </article>
        ))}
      </section>

      <footer style={{ marginTop: 48, color: "#667085", fontSize: 13 }}>
        Initial foundation · Web + Windows desktop · Shared Python API
      </footer>
    </main>
  );
}

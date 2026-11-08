import "./integrations.css";

import Link from "next/link";

import {
  Activity,
  ArrowDownToLine,
  ArrowUpRight,
  BookOpenCheck,
  Cable,
  CheckCircle2,
  CircleHelp,
  Code2,
  KeyRound,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Webhook,
} from "lucide-react";

const capabilities = [
  { icon: KeyRound, title: "API credentials", description: "Issue separate credentials for each connected application." },
  { icon: ShieldCheck, title: "Scoped permissions", description: "Grant only the candidate, assessment or result access an app needs." },
  { icon: Webhook, title: "Webhooks", description: "Notify external systems when exam and result events occur." },
  { icon: LockKeyhole, title: "Single sign-on", description: "Connect identity providers using OIDC or SAML." },
];

const roadmap = [
  { name: "REST API and API keys", status: "Foundation in progress", tone: "blue" },
  { name: "Candidate and course sync", status: "Planned", tone: "neutral" },
  { name: "Exam launch and result sync", status: "Planned", tone: "neutral" },
  { name: "Webhooks and SDKs", status: "Planned", tone: "neutral" },
];

export default function IntegrationsPage() {
  return (
    <main className="integration-shell">
      <aside className="integration-sidebar">
        <div className="brand-lockup"><span className="brand-mark">C</span><span>Intelligent CBT</span></div>
        <p className="sidebar-label">WORKSPACE</p>
        <Link className="sidebar-link" href="/">Overview</Link>
        <a className="sidebar-link" href="#connected-apps">Connected apps</a>
        <Link className="sidebar-link active" href="/integrations"><Cable size={17} /> Integrations</Link>
        <a className="sidebar-link" href="#developer-tools"><Code2 size={17} /> Developer tools</a>
        <div className="sidebar-bottom"><span className="avatar">SC</span><div><strong>School workspace</strong><small>Administrator view</small></div></div>
      </aside>

      <section className="integration-main">
        <header className="integration-topbar"><span>Workspace / Integrations</span><span className="environment-pill"><span /> Development environment</span></header>
        <div className="integration-content">
          <div className="page-heading-row">
            <div><p className="eyebrow">CONNECT YOUR SOFTWARE</p><h1>Integrations</h1><p className="page-description">Connect your existing school portal, LMS, SIS or custom application to Intelligent CBT.</p></div>
            <div className="preview-label"><CircleHelp size={15} /> Early access preview</div>
          </div>

          <section className="integration-hero">
            <div className="hero-copy"><div className="hero-icon"><Cable size={22} /></div><h2>One assessment engine.<br />Connected to your ecosystem.</h2><p>Keep your current systems. Integrate candidate records, launch examinations and receive released results through a secure API.</p><div className="hero-tags"><span><CheckCircle2 size={14} /> Tenant isolated</span><span><CheckCircle2 size={14} /> Permission scoped</span><span><CheckCircle2 size={14} /> Auditable</span></div></div>
            <div className="connection-visual"><div className="system-node"><BookOpenCheck size={21} /><span>School portal</span></div><div className="connector-line"><i /><i /><i /></div><div className="cbt-node"><span className="brand-mark">C</span><strong>CBT API</strong><small>Integration gateway</small></div><div className="connector-line"><i /><i /><i /></div><div className="system-node"><Activity size={21} /><span>Results & exams</span></div></div>
          </section>

          <div className="section-heading" id="connected-apps"><div><h2>Connected applications</h2><p>Applications authorised to access your CBT workspace.</p></div><span className="count-pill">0 applications</span></div>
          <div className="empty-apps"><div className="empty-icon"><Cable size={22} /></div><h3>No applications connected yet</h3><p>When application registration is enabled, you can create an integration, issue credentials and choose its permissions here.</p><span className="coming-soon"><RefreshCw size={13} /> Registration is not enabled yet</span></div>

          <div className="section-heading"><div><h2>Integration capabilities</h2><p>Security and connectivity features planned for the integration gateway.</p></div></div>
          <div className="capability-grid">{capabilities.map(({ icon: Icon, title, description }) => <article className="capability-card" key={title}><div className="capability-icon"><Icon size={18} /></div><h3>{title}</h3><p>{description}</p></article>)}</div>

          <div className="section-heading" id="developer-tools"><div><h2>Developer roadmap</h2><p>Implementation status of the integration foundation.</p></div><a className="docs-link" href="https://github.com/oghenenoghie/cbt/tree/main/docs/integrations" target="_blank" rel="noreferrer">View API documentation <ArrowUpRight size={14} /></a></div>
          <div className="roadmap-card">{roadmap.map((item, index) => <div className="roadmap-row" key={item.name}><div className="roadmap-index">0{index + 1}</div><strong>{item.name}</strong><span className={`roadmap-status ${item.tone}`}>{item.status}</span></div>)}</div>
          <div className="security-note"><LockKeyhole size={18} /><div><strong>Security comes first</strong><p>API secrets will be shown only once and stored as hashes. Each integration will be restricted to its school tenant and explicitly granted permissions.</p></div></div>
          <footer className="integration-footer"><span>Intelligent CBT · Integration centre</span><span><ArrowDownToLine size={13} /> API documentation is available in GitHub</span></footer>
        </div>
      </section>
    </main>
  );
}

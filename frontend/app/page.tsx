import Link from "next/link";
import ThemeToggle from "../components/theme-toggle";

export default function Welcome() {
  return <div className="entry-shell">
    <header className="entry-header"><span className="brand">Tomo</span><ThemeToggle /></header>
    <main className="entry-main">
      <div className="entry-copy">
        <span className="entry-eyebrow">A CALENDAR THAT ADAPTS WITH YOU</span>
        <h1>Make room for what matters.</h1>
        <p>Bring your tasks, routines and commitments together. Tell Tomo what changed and review a new plan before it touches your day.</p>
        <div className="entry-actions">
          <Link className="entry-primary" href="/demo">Try the demo <span aria-hidden="true">↗</span></Link>
          <Link className="entry-secondary" href="/sign-in">Sign in or create an account</Link>
        </div>
        <p className="entry-note">The demo is private to this browser and resets after seven days. No account needed.</p>
      </div>
      <div className="entry-preview" aria-label="Example Tomo plan">
        <div className="entry-preview-top"><strong>Your day, reworked.</strong><span>MON · 9:00 AM</span></div>
        <div className="entry-preview-row focus"><span>9:00–10:30</span><strong>Finish the case study</strong></div>
        <div className="entry-preview-row fixed"><span>11:00–12:00</span><strong>Design interview</strong></div>
        <div className="entry-preview-row routine"><span>1:00–1:45</span><strong>Go for a run</strong></div>
        <div className="entry-preview-note">“Move my workout to tonight.” <span>Review changes →</span></div>
      </div>
    </main>
    <footer className="entry-footer"><span>Plan clearly. Change freely.</span><span>Made for real life.</span></footer>
  </div>;
}

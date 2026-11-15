import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import type { LabStatus } from "../shared/api";
import { call } from "./lab";
import { Room } from "./Room";
import { Setup } from "./Setup";
import { Staff } from "./Staff";
import { ErrorText } from "./ui";

/** Which side to show: setting up, the exam room (students), or the staff side (after the PIN). */
function App() {
  const [status, setStatus] = useState<LabStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await call("status"));
    } catch (caught) {
      setError((caught as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // The staff side closes by itself after a while: notice, and go back to the exam room.
  useEffect(() => {
    if (!status?.staff) return;
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(timer);
  }, [status?.staff, refresh]);

  if (error) return <ErrorText error={error} />;
  if (!status) return null;
  if (!status.registered) return <Setup status={status} onChanged={setStatus} />;
  if (status.staff) return <Staff status={status} onLocked={setStatus} />;
  return <Room status={status} onStaff={setStatus} />;
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

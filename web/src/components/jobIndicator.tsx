import { useEffect, useRef, useState } from "react";
import { MdDownload, MdGraphicEq } from "react-icons/md";

import { api, type Job } from "../lib/api";

/** Downloads and renders in progress. Calls onChange whenever the count changes. */
export default function JobIndicator({ onChange }: { onChange: () => void }) {
  const [active, setActive] = useState<Job[]>([]);
  const prev = useRef(0);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const [pending, running] = await Promise.all([api.jobs("pending"), api.jobs("running")]);
        const jobs = [...running, ...pending].filter((j) => j.kind !== "scan");
        if (!stop) {
          if (jobs.length !== prev.current) onChange();
          prev.current = jobs.length;
          setActive(jobs);
        }
      } catch {
        /* the server may be restarting */
      }
      if (!stop) setTimeout(tick, prev.current ? 1000 : 2000);
    };
    void tick();
    return () => {
      stop = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const downloads = active.filter((j) => j.kind === "download").length;
  const renders = active.filter((j) => j.kind === "render").length;
  if (!downloads && !renders) return <span className="text-xs text-theme-500" data-testid="jobs-idle">idle</span>;
  return (
    <span className="flex items-center gap-2 text-xs text-theme-700 dark:text-theme-200" data-testid="jobs-active">
      {downloads > 0 && (
        <span className="flex items-center gap-0.5" title="Downloads in progress">
          <MdDownload /> {downloads}
        </span>
      )}
      {renders > 0 && (
        <span className="flex items-center gap-0.5" title="Renders in progress">
          <MdGraphicEq className="animate-pulse" /> {renders}
        </span>
      )}
    </span>
  );
}

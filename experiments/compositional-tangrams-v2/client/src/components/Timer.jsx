import { useStageTimer } from "@empirica/core/player/classic/react";
import {
  useStage
} from "@empirica/core/player/classic/react";
import React from "react";

export function Timer() {
  const timer = useStageTimer();
  const stage = useStage();

  let remaining;
  if (timer?.remaining || timer?.remaining === 0) {
    remaining = Math.round(timer?.remaining / 1000);
  }
  // Countdown shows on "selection" only, NOT on the description stages.
  //
  // The pre-test runs on a stage clock but the post-test is an exit step with no
  // clock at all. A visible countdown in one phase and not the other is an
  // asymmetry in exactly the comparison the primary DV rests on (pre->post
  // description distance, and description length as DV4), so neither phase shows
  // one. The truncation risk that motivated showing it is handled instead by the
  // late warning banner in Describe.jsx, which only appears when someone is
  // genuinely about to be cut off.
  const timed = stage.get("name") === "selection";
  const low = timed && remaining !== undefined && remaining <= 120;

  // Description stages render an empty slot, not "--:--". A placeholder clock
  // reads as broken, and the meaningful countdown there is the muted per-item
  // one inside Describe.
  if (!timed) return <div className="flex flex-col items-center" />;

  const time = humanTimer(remaining);
  
  return (
    <div className="flex flex-col items-center">
      <h1 className={`tabular-nums text-3xl font-semibold ${low ? "text-red-600" : "text-gray-500"}`}>
        {time}
      </h1>
    </div>
  );
}

function humanTimer(seconds) {
  if (seconds === null || seconds === undefined) {
    return "--:--";
  }

  let out = "";
  const s = seconds % 60;
  out += s < 10 ? "0" + s : s;

  const min = (seconds - s) / 60;
  if (min === 0) {
    return `00:${out}`;
  }

  const m = min % 60;
  out = `${m < 10 ? "0" + m : m}:${out}`;

  const h = (min - m) / 60;
  if (h === 0) {
    return out;
  }

  return `${h}:${out}`;
}

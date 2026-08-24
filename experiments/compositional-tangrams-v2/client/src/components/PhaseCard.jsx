import React from "react";

// Interstitial shown at phase boundaries so participants are never dropped into
// a new task without warning. Used before the pre-test, after the pre-test, and
// before the post-test.
//
// Deliberately requires a click: the point is a beat of orientation, not a
// timed splash. Nothing here is on the stage clock except the pre-test's own
// cap, which is generous enough that reading this cannot cost anyone the phase.
export function PhaseCard({ eyebrow, title, children, buttonLabel, onContinue }) {
  return (
    <div className="flex items-center justify-center w-full p-8">
      <div className="max-w-xl w-full text-center">
        {eyebrow && (
          <div className="text-sm font-semibold uppercase tracking-wide text-gray-400 mb-2">
            {eyebrow}
          </div>
        )}
        <h2 className="text-2xl font-semibold mb-4 text-gray-900">{title}</h2>
        <div className="text-gray-600 space-y-3 text-left mb-8">{children}</div>
        {onContinue && (
          <button
            onClick={onContinue}
            autoFocus
            className="px-8 py-3 rounded-md text-white font-semibold"
            style={{ backgroundColor: "#403f53" }}
          >
            {buttonLabel || "Continue"}
          </button>
        )}
      </div>
    </div>
  );
}

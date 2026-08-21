import { usePlayer } from "@empirica/core/player/classic/react";
import React, { useEffect, useRef, useState } from "react";

// Free-description test phase (design doc S4.3-4.5).
//
// One shape on screen, free text, no foils, no matcher, no feedback, no
// accuracy, no chat. An earlier design had arrays and a matcher here and they
// were deliberately removed -- do not add them back.
//
// The item list is walked CLIENT-SIDE and entirely locally: `idx` is React
// state, not a shared attribute, so the two partners never wait on each other.
//
// This component is used in TWO places and must not depend on round or stage:
//   - pre-test, inside the game (a round + stage; onComplete submits the stage)
//   - post-test, as an EXIT STEP after the game has ended (onComplete calls next)
// The exit-step placement is what lets a participant finish and leave while
// their partner is still describing. Everything it needs -- the item list and
// the rotation -- lives on the player scope, set at game start.

const PROMPT = "How would you describe this shape to another person?";

export function Describe({ phase, onComplete, doneMessage }) {
  const player = usePlayer();

  const itemsKey = `${phase}Items`;
  const responsesKey = `${phase}Responses`;

  // Length is whatever the server handed us: 20 for comp, but only 8 for the
  // noncomp pre-test (S4.6). Never hardcode 20.
  const items = player.get(itemsKey) || [];

  const [idx, setIdx] = useState(0);
  const [text, setText] = useState("");
  const [done, setDone] = useState(false);
  const shownAt = useRef(Date.now());
  const inputRef = useRef(null);

  const item = items[idx];
  // Read from the player, not the game: the game scope is not reliably available
  // once the post-test runs as an exit step.
  const rotation = player.get("rotation") || 0;

  // Preload the NEXT shape while this one is being described, so the image is
  // already in cache when the participant advances.
  useEffect(() => {
    const next = items[idx + 1];
    if (next) {
      const img = new Image();
      img.src = next.url;
    }
  }, [idx, items]);

  // Reset the per-item clock and refocus whenever the item changes.
  useEffect(() => {
    shownAt.current = Date.now();
    inputRef.current?.focus();
  }, [idx]);

  const submitItem = () => {
    const trimmed = text.trim();
    if (!trimmed || done || !item) return;

    const prior = player.get(responsesKey) || [];
    player.set(responsesKey, [
      ...prior,
      {
        image: item.image,
        label: item.label,
        cell: item.cell,
        top: item.top,
        bottom: item.bottom,
        order: idx,
        text: trimmed,
        shownAt: shownAt.current,
        submittedAt: Date.now(),
      },
    ]);

    if (idx + 1 >= items.length) {
      setDone(true);
      // Marks a genuine completion, which is what exitSteps routes on. Empirica's
      // own `ended` reason says "game ended" for normal finishes too, so it
      // cannot distinguish completion from dropout. See App.jsx.
      if (phase === "posttest") player.set("completedStudy", true);
      onComplete();
    } else {
      setIdx(idx + 1);
      setText("");
    }
  };

  const onKeyDown = (e) => {
    // Enter submits, shift+Enter makes a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitItem();
    }
  };

  if (!items.length) {
    return <div className="p-8 text-gray-500">Loading items…</div>;
  }

  if (done) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-center">
        <h2 className="text-2xl font-semibold mb-2">
          Finished — thank you!
        </h2>
        <p className="text-gray-600 max-w-md">
          {doneMessage ||
            `You have described all ${items.length} shapes. This will continue automatically.`}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center p-6 w-full">
      <div className="text-sm font-semibold uppercase tracking-wide text-gray-400 mb-1">
        {phase === "pretest" ? "Part 1 of 3" : "Part 3 of 3"}
      </div>
      <div className="text-gray-600 mb-4">
        Shape {idx + 1} of {items.length}
      </div>

      <div
        style={{
          width: "30vh",
          height: "30vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#fff",
          border: "1px solid #e5e7eb",
          marginBottom: "1.25rem",
        }}
      >
        <img
          src={item.url}
          alt="Shape to describe"
          style={{
            maxWidth: "80%",
            maxHeight: "80%",
            transform: `rotate(${rotation}deg)`,
            display: "block",
          }}
        />
      </div>

      <label className="text-lg font-medium mb-2 text-center max-w-lg">
        {PROMPT}
      </label>
      <p className="text-sm text-gray-500 mb-3 text-center max-w-lg">
        Describe it so that another person could pick it out.
      </p>

      <textarea
        ref={inputRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        rows={3}
        className="w-full max-w-lg border rounded-md p-2 mb-3"
        placeholder="Type your description…"
      />

      <button
        onClick={submitItem}
        disabled={!text.trim()}
        className="px-6 py-2 rounded-md text-white font-semibold disabled:opacity-40"
        style={{ backgroundColor: "#403f53" }}
      >
        {idx + 1 >= items.length ? "Finish" : "Next shape"}
      </button>
    </div>
  );
}

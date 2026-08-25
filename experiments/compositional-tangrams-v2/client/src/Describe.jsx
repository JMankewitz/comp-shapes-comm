import { usePlayer } from "@empirica/core/player/classic/react";
import React, { useEffect, useRef, useState } from "react";
import { PhaseCard } from "./components/PhaseCard";

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

export function Describe({ phase, onComplete, doneMessage, secondsPerItem = 60 }) {
  const player = usePlayer();

  const itemsKey = `${phase}Items`;
  const responsesKey = `${phase}Responses`;

  // Length is whatever the server handed us: 20 for comp, but only 8 for the
  // noncomp pre-test (S4.6). Never hardcode 20.
  const items = player.get(itemsKey) || [];

  // Resume where the participant left off. `idx` is local React state, so a page
  // refresh used to reset it to 0 -- restarting the list at shape 1 and appending
  // duplicate responses for everything already described. Seed it from what is
  // already stored on the player instead, and skip answered items.
  const answered = new Set((player.get(responsesKey) || []).map((r) => r.image));
  const firstUnanswered = items.findIndex((it) => !answered.has(it.image));

  const [idx, setIdx] = useState(firstUnanswered === -1 ? items.length : firstUnanswered);
  const [text, setText] = useState("");
  const [done, setDone] = useState(false);       // reached the end of the list
  const submittedKey = `${phase}Submitted`;
  // Player-scoped: refreshing while waiting on a partner must not drop back to
  // the completion card (and let onComplete fire twice).
  const [submitted, setSubmitted] = useState(!!player.get(submittedKey));
  const shownAt = useRef(Date.now());
  const inputRef = useRef(null);
  const [secsLeft, setSecsLeft] = useState(secondsPerItem);

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
    setSecsLeft(secondsPerItem);
    inputRef.current?.focus();
  }, [idx, secondsPerItem]);

  // Per-item countdown. Bounding each ITEM rather than the phase means a slow
  // start cannot eat the whole budget, the total is deterministic
  // (items x secondsPerItem), and nobody is left waiting on a partner who walked
  // away. Runs client-side, so the post-test gets the same treatment as the
  // pre-test even though it is an exit step with no stage clock.
  useEffect(() => {
    if (done || !item) return;
    const id = setInterval(() => setSecsLeft((v) => v - 1), 1000);
    return () => clearInterval(id);
  }, [idx, done, item]);

  useEffect(() => {
    if (secsLeft <= 0 && !done && item) submitItem({ auto: true });
  }, [secsLeft]);

  // `auto` = the per-item timer expired. Whatever has been typed is kept, even
  // if it is empty or half-finished: the alternative is losing the response and
  // silently truncating the phase, which is what the first pilot run did.
  const submitItem = ({ auto = false } = {}) => {
    const trimmed = text.trim();
    if (done || !item) return;
    if (!trimmed && !auto) return; // manual submit still requires some text

    const prior = player.get(responsesKey) || [];
    if (prior.some((r) => r.image === item.image)) {
      // Already recorded (e.g. refresh landed mid-write). Advance, never duplicate.
      setIdx(idx + 1);
      setText("");
      return;
    }
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
        // Flagged so the analysis can identify (and if needed exclude) responses
        // the participant did not choose to submit.
        autoSubmitted: auto,
      },
    ]);

    if (idx + 1 >= items.length) {
      setDone(true); // ack card next; onComplete fires when they click through
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

  // A refresh after the last item lands here: everything answered, so go straight
  // to the acknowledgement card rather than an empty list.
  useEffect(() => {
    if (items.length && idx >= items.length && !done) setDone(true);
  }, [idx, items.length, done]);

  const finish = () => {
    setSubmitted(true);
    player.set(submittedKey, true);
    // Marks a genuine completion, which is what exitSteps routes on. Empirica's
    // own `ended` reason says "game ended" for normal finishes too, so it cannot
    // distinguish completion from dropout. See App.jsx.
    if (phase === "posttest") player.set("completedStudy", true);
    onComplete();
  };

  if (!items.length) {
    return <div className="p-8 text-gray-500">Loading items…</div>;
  }

  // Submitted: the partner-wait screen (pre-test only -- the post-test navigates
  // away on finish, so this never renders there).
  if (submitted) {
    return (
      <PhaseCard eyebrow="Part 1 complete" title="Waiting for your partner">
        <p>
          {doneMessage ||
            "Your partner is still working through their own shapes. The next part will begin automatically as soon as they finish."}
        </p>
        <p className="text-sm text-gray-500">
          You do not need to do anything — please keep this tab open. This usually
          takes a minute or two.
        </p>
        {/* Two pilot participants waited 30 and 45 minutes here before giving up,
            because nothing on screen said the wait was bounded. The server-side
            watchdog now ends the game if a partner goes silent, but saying so
            matters as much as doing it: people return studies when they cannot
            tell a slow wait from a broken one. */}
        <p className="text-sm text-gray-500">
          If your partner has left, this will end on its own within a few minutes
          and you will still be paid for the work you have done. You do not need to
          message us or return the study.
        </p>
      </PhaseCard>
    );
  }

  // Reached the end of the list, but has not clicked through yet.
  if (done) {
    const isPre = phase === "pretest";
    return (
      <PhaseCard
        eyebrow={isPre ? "Part 1 of 3 complete" : "Part 3 of 3 complete"}
        title={`You have described all ${items.length} shapes.`}
        buttonLabel={isPre ? "Continue to Part 2" : "Continue to the final survey"}
        onContinue={finish}
      >
        {isPre ? (
          <>
            <p>
              Next you will play the <b>matching game</b> with your partner. One of
              you describes a shape and the other picks it out, and you swap roles
              each round.
            </p>
            <p>
              This part is where your <b>bonus</b> comes from — $0.03 for each
              correct match.
            </p>
            <p className="text-sm text-gray-500">
              If your partner is still finishing their shapes, you will wait a
              moment before the game starts.
            </p>
          </>
        ) : (
          <p>That is the last of the shapes. Just a short survey to finish up.</p>
        )}
      </PhaseCard>
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

      <div
        className={`text-sm mb-3 tabular-nums transition-colors ${
          secsLeft <= 15 ? "text-amber-600 font-semibold" : "text-gray-500"
        }`}
      >
        {secsLeft <= 15
          ? `${Math.max(secsLeft, 0)}s — your answer will be saved automatically`
          : `${Math.floor(secsLeft / 60)}:${String(Math.max(secsLeft, 0) % 60).padStart(2, "0")}`}
      </div>

      <button
        onClick={() => submitItem()}
        disabled={!text.trim()}
        className="px-6 py-2 rounded-md text-white font-semibold disabled:opacity-40"
        style={{ backgroundColor: "#403f53" }}
      >
        {idx + 1 >= items.length ? "Finish" : "Next shape"}
      </button>
    </div>
  );
}

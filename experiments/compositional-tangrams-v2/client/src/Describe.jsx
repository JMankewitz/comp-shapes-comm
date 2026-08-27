import { usePlayer, usePlayers } from "@empirica/core/player/classic/react";
import React, { useEffect, useRef, useState } from "react";
import { PhaseCard } from "./components/PhaseCard";

// Reuses the game-start bell. This fires at exactly one moment: the participant
// has answered every item and the study is now waiting on a single click.
//
// A dyad was lost this way. Both partners wrote all 20 descriptions; one had 12
// of theirs autosubmitted by the per-item timer, meaning they were repeatedly
// away when it fired. Their last item autosubmitted while they were away, the
// acknowledgement card came up, nobody clicked, and three minutes later the
// watchdog killed the game as `pretestAbandoned` -- two complete pre-tests
// thrown away one click short of training.
//
// Advancing automatically would be worse, not better: an away participant would
// be carried into 48 training rounds and take their partner's session with them.
// The click is the attention check. So make it audible instead of silent.
const attentionBell = new Audio("bell.mp3");
attentionBell.volume = 1.0;

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
  // usePlayers() is only meaningful inside a live game. The post-test runs as an
  // EXIT STEP after the game has ended, so this can be undefined there -- the
  // hook still has to be called unconditionally, hence the guards rather than a
  // conditional call. Only the pre-test has a partner to wait on at all.
  const players = usePlayers();
  const partner = (players || []).find((p) => p && p.id !== player.id);
  const partnerProgress =
    phase === "pretest" && partner
      ? Number(partner.get("pretestProgress") || 0)
      : null;

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
  const alerted = useRef(false);
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
    // { private: true } -- the descriptions stay on this participant's client and
    // the server, and are NOT synced to their partner. Empirica syncs player
    // scopes to every client in the game by default (that is what usePlayers()
    // reads), so without this a participant could read their partner's
    // descriptions in devtools WHILE WRITING THEIR OWN. DV5 is partner
    // alignment; that is the one thing that must not leak.
    //
    // It also cuts traffic: this array is re-sent on every submission, so it was
    // being pushed to two clients instead of one, growing with each item.
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
    ], { private: true });

    // Pre-test only, and deliberately NOT private: a bare count is what the
    // waiting partner sees. The post-test runs as an exit step after the game
    // has ended, so there is no partner to sync to and no one to read it.
    if (phase === "pretest") {
      player.set("pretestProgress", prior.length + 1);
    }

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

  // The participant has finished every item and the study is waiting on one
  // click. If they are on another tab -- which is exactly the state that loses
  // dyads here -- nothing on this page can reach them, so ring the bell AND
  // flash the tab title, which is visible without switching windows.
  //
  // Fires once per phase (`alerted`), and only while the tab is hidden or until
  // they come back. Autoplay may be blocked if the participant never interacted
  // with the page, hence the catch; by this point they have typed 20 answers, so
  // the gesture requirement is satisfied in practice.
  useEffect(() => {
    if (!done || submitted || alerted.current) return;
    alerted.current = true;

    attentionBell.play().catch(() => {});

    const original = document.title;
    let on = false;
    const flash = setInterval(() => {
      on = !on;
      document.title = on ? "\u25CF Your turn \u2014 click to continue" : original;
    }, 1000);
    const stop = () => {
      clearInterval(flash);
      document.title = original;
    };
    // Any sign they are back: focus, or the tab becoming visible again.
    window.addEventListener("focus", stop, { once: true });
    document.addEventListener("visibilitychange", function vis() {
      if (!document.hidden) {
        document.removeEventListener("visibilitychange", vis);
        stop();
      }
    });
    return stop;
  }, [done, submitted]);

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
        {/* A live count of the partner's progress. The complaint this answers is
            not "the wait is long" but "I cannot tell a slow partner from a
            broken study" -- a number that moves distinguishes them at a glance.
            Only the COUNT crosses between clients, never the descriptions. */}
        {partnerProgress !== null ? (
          <div className="mt-2 mb-1">
            <div className="flex justify-between text-sm text-gray-600 mb-1">
              <span>Your partner&rsquo;s progress</span>
              <span className="tabular-nums font-medium">
                {partnerProgress} / {items.length}
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-gray-200 overflow-hidden">
              <div
                className="h-full rounded-full bg-blue-500 transition-all duration-500"
                style={{
                  width: `${Math.min(100, (partnerProgress / Math.max(1, items.length)) * 100)}%`,
                }}
              />
            </div>
          </div>
        ) : null}
        <p className="text-sm text-gray-500">
          You do not need to do anything — please keep this tab open. Most people
          finish within a few minutes of each other, but a partner who is taking
          their time can take up to about twenty minutes. You are being paid for
          this waiting time.
        </p>
        {/* Two pilot participants waited 30 and 45 minutes here before giving up,
            because nothing on screen said the wait was bounded. The server-side
            watchdog ends the game if a partner goes SILENT for three minutes --
            but it deliberately does not fire for a partner who is simply slow,
            because each new answer resets the timer and that is not abandonment.
            The old copy promised "a few minutes" for both cases, so a participant
            waiting on a slow partner was told something plainly untrue: the
            pre-test is 20 items at up to 60s each, so an active partner can take
            20 minutes. One participant messaged after 10, having been told it
            would be a few. Name the real bound, and say the wait is paid. */}
        <p className="text-sm text-gray-500">
          If your partner has stopped altogether, this ends on its own within a
          few minutes and you will still be paid for the work you have done. You
          do not need to message us or return the study.
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

import { usePlayer } from "@empirica/core/player/classic/react";
import React from "react";
import { Describe } from "../Describe";

// Post-test as an EXIT STEP rather than a game round.
//
// The post-test is the last thing a participant does and nothing after it
// depends on their partner, so there is no reason to hold a fast finisher while
// the slower one works. As a round it paced to max(A, B); here each participant
// walks their own list and goes straight to the exit survey.
//
// Everything it needs is on the player scope, written at game start:
// `posttestItems` (already shuffled per player) and `rotation`. Responses are
// appended to `posttestResponses` exactly as before, so the export is unchanged.
export function Posttest({ next }) {
  const player = usePlayer();

  // A dyad that never finished training has nothing to post-test on. App.jsx
  // gates on this too; the guard here keeps the component safe on its own.
  if (!player.get("finishedTraining")) {
    next();
    return null;
  }

  return (
    <div className="h-full w-full flex items-center justify-center overflow-auto">
      <Describe
        phase="posttest"
        onComplete={next}
        doneMessage="That is the last shape. Continuing to a short final survey."
      />
    </div>
  );
}

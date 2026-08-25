import { usePlayer } from "@empirica/core/player/classic/react";
import React from "react";
import { COMPLETION_CODES } from "../completionCodes";

// The very last screen, shown after the exit survey is submitted.
//
// Empirica's default finished page is generic, which is a problem here because
// three different outcomes need three different instructions. In the first pilot
// wave ~10 participants messaged asking which code to use or whether to return —
// every one of those is a person who reached the end and still did not know what
// to do. This is the screen that answers that, at the moment they need it.
//
// Which outcome a participant is in is readable from their own attributes:
//   completedStudy   -> finished the post-test
//   gameID present   -> reached a game but it ended early
//   neither          -> never matched into a game
export function Finished() {
  const player = usePlayer();

  const completed = player.get("completedStudy");
  const hadGame = Boolean(player.get("gameID"));
  const bonus = player.get("bonus") || 0;

  let title, code, body, action;

  if (completed) {
    title = "All done — thank you!";
    code = COMPLETION_CODES.COMPLETE;
    body = (
      <>
        <p>
          You completed all three parts of the study. Your bonus of{" "}
          <strong>${bonus.toFixed(2)}</strong> from the matching game will be paid
          along with the base payment.
        </p>
      </>
    );
    action = "submit";
  } else if (hadGame) {
    title = "Thank you — your session ended early";
    code = COMPLETION_CODES.INCOMPLETE;
    body = (
      <>
        <p>
          The game ended before the final part, usually because a partner
          disconnected. <strong>This is not your fault</strong> and does not affect
          your payment.
        </p>
        <p>
          You will be paid for the work you completed
          {bonus > 0 ? (
            <>
              , including the <strong>${bonus.toFixed(2)}</strong> bonus you earned
            </>
          ) : null}
          .
        </p>
      </>
    );
    action = "submit";
  } else {
    title = "Thank you for your time";
    code = null;
    body = (
      <>
        <p>
          We were not able to match you with a partner. This study needs two people
          at once, so sometimes there is nobody available.
        </p>
        <p>
          We will send you a <strong>bonus payment of $2.50</strong> for the time
          you spent, usually within 24 hours.
        </p>
      </>
    );
    action = "return";
  }

  return (
    <div className="h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="max-w-xl w-full text-center">
        <h2 className="text-3xl font-semibold text-gray-900 mb-4">{title}</h2>
        <div className="text-gray-600 space-y-3 text-left mb-8">{body}</div>

        {action === "submit" ? (
          <div className="rounded-md border border-gray-300 bg-white p-6">
            <div className="text-sm uppercase tracking-wide text-gray-400 mb-2">
              Your completion code
            </div>
            <div className="text-3xl font-mono font-bold tracking-widest text-gray-900 mb-3">
              {code}
            </div>
            <p className="text-sm text-gray-600">
              Copy this code into Prolific to submit the study. If you were returned
              to Prolific automatically, you do not need to do anything else.
            </p>
          </div>
        ) : (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-6">
            <div className="text-lg font-semibold text-amber-900 mb-2">
              Please RETURN this submission on Prolific
            </div>
            <p className="text-sm text-amber-900">
              There is no completion code for this outcome. Returning does not count
              against you, and it frees the slot so someone else can be matched. Your
              $2.50 will arrive as a bonus payment.
            </p>
          </div>
        )}

        <p className="text-xs text-gray-400 mt-6">
          You may now close this window.
        </p>
      </div>
    </div>
  );
}

import { Loading } from "@empirica/core/player/react";
import React, { useEffect, useState } from "react";

// Replaces Empirica's generic <Loading /> inside the game.
//
// Empirica renders the loading screen whenever the page is not ready for the
// CURRENT stage -- that is, until the server has created both players' objects
// for it. Those are created inside the server's single callback queue, so when
// the server is busy a participant sits on a bare spinner with no explanation,
// and the natural response is to reload. Reloading makes it worse: it opens
// fresh subscriptions against a server that is already behind (2026-09-11: the
// wave stalled to 123-271 s per round, and participants who refreshed did not
// recover faster).
//
// So: the same spinner, and after a few seconds a plain explanation. The
// wording is deliberately neutral because this screen also appears briefly in
// ordinary places (game start, between phases), and only becomes alarming when
// it lasts.
const SLOW_AFTER_MS = 4000;

export function CatchingUp() {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(id);
  }, []);

  return (
    <>
      <Loading />
      {slow && (
        <div
          style={{
            position: "fixed",
            left: 0,
            right: 0,
            bottom: "18%",
            textAlign: "center",
            padding: "0 24px",
          }}
        >
          <p className="text-gray-600" style={{ maxWidth: 480, margin: "0 auto" }}>
            Still loading. Please wait &mdash; reloading the page can make it
            slower. Your progress is saved.
          </p>
        </div>
      )}
    </>
  );
}

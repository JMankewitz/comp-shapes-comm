import { usePlayer } from "@empirica/core/player/classic/react";
import { Loading } from "@empirica/core/player/react";
import React, { useEffect, useState } from "react";
import { LOBBY_MINUTES, PAY, money } from "../tiers";

// Replaces Empirica's default lobby ("Waiting for other players / Please wait
// for the game to be ready"), which says nothing about what is being waited for
// or for how long.
//
// The countdown runs in the browser. The server does keep a per-player lobby
// timer, but it is never shared with participants, so the page cannot read it;
// instead we count from the moment this screen is first shown, which is when the
// server's timer starts (both begin when the participant finishes the
// instructions). The start time is stored on the player so a refresh resumes the
// countdown instead of restarting it, using the participant's own clock for both
// ends so clock skew cannot distort it.
const LOBBY_MS = LOBBY_MINUTES * 60 * 1000;

const clock = (ms) => {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export function WaitingLobby() {
  const player = usePlayer();
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (player && !player.get("lobbyEnteredAt")) {
      player.set("lobbyEnteredAt", Date.now());
    }
  }, [player]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!player) return <Loading />;

  const enteredAt = player.get("lobbyEnteredAt");
  const left = enteredAt ? LOBBY_MS - (now - enteredAt) : LOBBY_MS;
  const expired = left <= 0;

  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="text-center" style={{ maxWidth: 520 }}>
        <h3 className="text-lg font-medium text-gray-900">Waiting for a partner</h3>
        <p className="mt-3 text-gray-600">
          The moment another participant is ready, we will pair you with them and
          the game will start automatically. Please keep this tab open and your
          sound on &mdash; a sound plays when your game begins.
        </p>

        {!expired ? (
          <>
            <div
              className="mt-6 tabular-nums text-4xl font-semibold text-gray-700"
              aria-live="off"
            >
              {clock(left)}
            </div>
            <p className="mt-1 text-sm text-gray-500">
              You may wait up to {LOBBY_MINUTES} minutes in total.
            </p>
          </>
        ) : (
          <p className="mt-6 text-gray-600">
            We could not find you a partner in time. One moment while we take
            you to the next step.
          </p>
        )}

        <p className="mt-6 text-sm text-gray-500">
          If no partner arrives, you will still be paid {money(PAY.LOBBY)} for
          your time, and we will explain how to claim it.
        </p>
      </div>
    </div>
  );
}

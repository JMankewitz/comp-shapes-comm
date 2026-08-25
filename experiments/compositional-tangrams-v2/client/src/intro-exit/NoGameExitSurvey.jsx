import React from "react";
import { usePlayer } from "@empirica/core/player/classic/react";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";
import { PAY, money } from "../tiers";

// Shown to players Empirica never assigned to a game. Two cases land here, and
// they are compensated differently, so the page must not promise one number to
// both:
//
//   * turned away at entry -- never saw an intro screen, so no time was spent
//     and nothing is owed. `intro` is written only once a player enters the
//     intro flow, which makes its absence the marker for this case.
//   * got partway through the consent/quiz before being turned away -- real
//     effort, paid a small amount for it.
//
// Neither reached a lobby, so do not describe their wait as a lobby wait.
const NO_LOBBY_PAY = money(PAY.NO_LOBBY);

export function NoGameSurvey({ next }) {
  const player = usePlayer();
  const sawIntro = player.get("intro") !== undefined;

  function handleSubmit(event) {
    event.preventDefault();
    player.set("exitSurvey", {
      gamefailed: "nogame",
      sawIntro,
    });
    next();
  }

  return (
    <div className="py-8 max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
      <Alert title="No Game Available">
        <p>
          Unfortunately, all of the available sessions had already filled by the
          time you arrived, so we were not able to place you in a game. This is
          not something you did — it depends on how many other participants
          happen to be starting at the same moment.
        </p>
      </Alert>

      <Alert title="What to do now">
        <p>
          <strong>Please RETURN this submission on Prolific.</strong> Returning
          does not count against you, and it frees the slot so another
          participant can be matched.
        </p>
        {sawIntro ? (
          <p className="pt-1">
            We will still send you a{" "}
            <strong>bonus payment of {NO_LOBBY_PAY}</strong> for the time you
            spent getting started, usually within 24 hours. Returning the
            submission does not prevent this. You do not need a completion code,
            and you do not need to do anything else.
          </p>
        ) : (
          <p className="pt-1">
            You do not need a completion code, and you do not need to do
            anything else.
          </p>
        )}
        <p className="pt-1">
          Thank you for your time and willingness to participate in our study.
        </p>
      </Alert>

      <form onSubmit={handleSubmit}>
        <div className="mt-8">
          <Button type="submit">Submit</Button>
        </div>
      </form>
    </div>
  );
}

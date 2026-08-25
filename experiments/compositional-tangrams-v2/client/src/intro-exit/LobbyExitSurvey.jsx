import React from "react";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";
import { PAY, money } from "../tiers";

// Shown to players Empirica assigned to a game whose partner never arrived, so
// the game never started. Empirica marks these `ended = "lobby timed out"`, and
// that string is only ever written when `game.hasStarted` is false (see
// expiredIndividualLobbyTimeout in @empirica/core) -- so these participants
// provably produced no data.
//
// They must NOT be given a completion code. Approving a submission on Prolific
// pays the full study reward; these participants are owed the flat lobby
// amount, which is paid as a bonus after they return. Deliberately no exit
// survey either: they contributed no data, so there is nothing to ask them.
const LOBBY_PAY = money(PAY.LOBBY);

export function LobbyExitSurvey({ next, noPartner = true }) {
  return (
    <div className="py-8 max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
      <Alert title={noPartner ? "No Partner Was Available" : "Session Did Not Continue"}>
        {noPartner ? (
          <p>
            Thank you for waiting. Unfortunately no other participant became
            available to pair with you, so the study was not able to begin. This
            is not something you did — it depends on how many people happen to
            be starting at the same time.
          </p>
        ) : (
          <p>
            Your session ended without any responses being recorded, so there is
            no study data to submit. If you ran into a technical problem, please
            message us on Prolific and we will sort it out.
          </p>
        )}
      </Alert>

      <Alert title="How to be paid for your time">
        <p>
          <strong>Please RETURN this submission on Prolific.</strong> Returning
          does not count against you, and it frees the slot for another
          participant.
        </p>
        <p className="pt-1">
          We will send you a <strong>bonus payment of {LOBBY_PAY}</strong> for
          your time, usually within 24 hours. Returning the
          submission does not prevent this. There is no completion code for this
          study, and you do not need to do anything else.
        </p>
        <p className="pt-1">
          Thank you for your time and willingness to participate in our study.
        </p>
      </Alert>

      <div className="mt-8">
        <Button handleClick={next}>Finish</Button>
      </div>
    </div>
  );
}

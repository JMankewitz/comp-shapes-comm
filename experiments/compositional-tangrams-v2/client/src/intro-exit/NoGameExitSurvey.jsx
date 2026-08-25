import React from "react";
import { usePlayer } from "@empirica/core/player/classic/react";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";

export function NoGameSurvey({ next }) {

  const player = usePlayer();

  function handleSubmit(event) {
    event.preventDefault();
    player.set("exitSurvey", {
      "gamefailed": "nogame"
    })
    next();
  }

  return (
    <div className="py-8 max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
      <Alert title="No Game Available">
        <p>
          Unfortunately, we were unable to match you with other participants for a game or experienced an error. You will still be compensated for your time spent in the waiting lobby.
          
        </p>
      </Alert>
      <Alert title="How to be paid for your time">
        <p>
          <strong>Please RETURN this submission on Prolific.</strong> Returning does
          not count against you, and it frees the slot so another participant can be
          matched.
        </p>
        <p className="pt-1">
          We will send you a <strong>bonus payment of $2.50</strong> for the time you
          spent, usually within 24 hours. You do not need a completion code, and you
          do not need to do anything else.
        </p>
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
import {
  usePlayer,
  useRound,
  useStage,
} from "@empirica/core/player/classic/react";
import React from "react";
import { Avatar } from "./components/Avatar";
import { Timer } from "./components/Timer";

export function Profile() {
  const player = usePlayer();
  const round = useRound();
  const stage = useStage();

  const score = (player.get("score") ?? 0).toFixed(2);
  const isTraining = round?.get("phase") === "training";

  if (stage.get("name") == "feedback") {
    let timer = "--.--"
  }

  return (
    <div className="min-w-lg md:min-w-2xl mt-2 m-x-auto px-3 py-2 text-gray-500 rounded-md grid grid-cols-3 items-center border-.5">
      <div className="leading-tight ml-1">
        <div className="text-gray-600 font-semibold">
        {isTraining ? "Round: " + (round.get("repNum") + 1) + " / " + (round.get('reps')) : ""}
        </div>
        <div className="text-gray-600 font-semibold">
        {/* was hardcoded "/ 16"; blocks are 12 trials under Exp 2 */}
        {isTraining
          ? "Trial: " + round.get("targetNum") + " / " + (round.get("numTrialsPerBlock") ?? "")
          : (round ? (round.get("phase") === "pretest" ? "Part 1 of 3" : "Part 3 of 3") : "")}
        </div>
        <div className="text-empirica-500 font-medium">
          {isTraining && stage ? stage.get("name") : ""}
        </div>
      </div>

      <Timer />

      <div className="flex space-x-3 items-center justify-end">
        <div className="flex flex-col items-center">
          <div className="text-xs font-semibold uppercase tracking-wide leading-none text-gray-400">
            Score
          </div>
          <div className="text-3xl font-semibold !leading-none tabular-nums">
            {"$" + score}
          </div>
        </div>
        <div className="h-11 w-11">
          <Avatar player={player} />
        </div>
      </div>
    </div>
  );
}

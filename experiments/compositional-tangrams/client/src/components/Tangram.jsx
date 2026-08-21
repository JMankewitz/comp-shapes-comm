import React from "react";
import _ from "lodash";

export function Tangram(props) {
  const {
    tangram,
    tangram_num,
    round,
    stage,
    game,
    player,
    players,
    target,
    preloadedImage,
    ...rest
  } = props;

  const handleClick = () => {
    if (stage.get("name") !== "selection") {
      console.warn("Attempt to click outside selection stage");
      return;
    }

    // Falsy test, not `!== ''`. `selection` is initialised at game creation, but
    // if it is ever absent this reads `undefined`, and a strict comparison would
    // silently swallow every click. See design doc S6.7.
    const current = round.get("selection");
    if (current && current !== tangram) {
      console.warn("Player already made selection", {attempted_selection: tangram,
        selected: current});
      return; //prevent multiple clicks
    }

    const partnerID = player.get("partner");
    const partner = players.find((p) => p.id === partnerID);
    const speakerMsgs = _.filter(round.get("chat"), (msg) => {
      return (
        msg.sender.id === player.get("partner") &&
        partner.get("role") === "director"
      );
    });

    if (player.get("role") !== "matcher") return;

    // Deliberate gate: the matcher may not choose until the director has said
    // something (S4.3 rationale -- prevents guessing before a description). But
    // the failure was silent and looked identical to a frozen page, which is
    // what participants reported. Surface it instead.
    if (speakerMsgs.length === 0) {
      round.set("clickBlockedAt", Date.now());
      return;
    }

    if (stage.get("name") === "selection" && (!current || current === tangram)) {
      // ITEM 7 (S6.6): client-side selection timestamp. Round start/end alone
      // cannot separate matcher-decide from transition from lag, and without
      // this there is no way to distinguish "clicked and waited" from "never
      // clicked" -- the ambiguity behind the 2.93% of rounds that recorded a
      // response yet still ran to the stage cap.
      round.set("selectionMadeAt", Date.now());
      round.set("selection", tangram);
      player.stage.set("submit", true);
      partner.stage.set("submit", true);
    }
  };

  const row = 1 + Math.floor(tangram_num / 2);
  const column = 1 + (tangram_num % 2);
  const rotation = game.get("rotation") || 0;

  const isCorrect = round.get("selection") === target;

  // Determine the box color
  const borderColor = (() => {
    if (stage.get("name") === "selection") {
      if (
        player.get("role") === "director" &&
        !round.get("selection") &&
        tangram === target
      ) {
        return "#000"; // Black for target selection highlight
      }
    } else if (stage.get("name") === "feedback") {
      if (tangram === target) {
        return isCorrect ? "green" : "red"; // Green if correct, red if incorrect
      }
    }
    return "transparent"; // Default border color
  })();


  return (
    <div
      onClick={handleClick}
      style={{
        width: "25vh",
        height: "25vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gridRow: row,
        gridColumn: column,
        margin: "15px",
        border: "10px solid",
        borderColor: borderColor,
        boxSizing: "border-box",
        position: "relative",
        backgroundColor: "#fff",
      }}
    >
      <img
        src={tangram}
        alt={`Tangram shape: ${tangram}`}
        style={{
          maxWidth: "80%",
          maxHeight: "80%",
          transform: `rotate(${rotation}deg)`,
          display: "block",
        }}
      />
    </div>
  );
}
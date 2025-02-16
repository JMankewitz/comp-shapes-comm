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

    if (round.get("selection") !== '' && round.get("selection") !==tangram){
      console.warn("Player already made selection", {attempted_selection: tangram, 
        selected: round.get("selection")});
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

    if (
      stage.get("name") === "selection" &&
      speakerMsgs.length > 0 &&
      (round.get("selection") === "" || round.get("selection") === tangram) &&
      player.get("role") === "matcher"
    ) {
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
        round.get("selection") === "" &&
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
import {
  useGame,
  usePlayer,
  usePlayers,
  useRound,
  useStage
} from "@empirica/core/player/classic/react";
import _ from "lodash";

import { Loading } from "@empirica/core/player/react";
import React, { useState, useEffect, useMemo } from "react";
import { Tangram } from "./components/Tangram.jsx";

export function Task() {
  const game = useGame();
  const player = usePlayer();
  const players = usePlayers();
  const round = useRound();
  const stage = useStage();
  
  const target = round.get("target"); // list of top and bottom shapes
  let tangramURLs = round.get("tangramURLs") || [];
  const [preloadedImages, setPreloadedImages] = useState({});

  useEffect(() => {
    const images = {};
    tangramURLs.forEach((url) => {
      const img = new Image();
      img.src = url;
      images[url] = img;
    });
    setPreloadedImages(images);
  }, [tangramURLs]);

  //console.log(player.get("role"))
  let finalTangramURLs = tangramURLs;
  if (player.get("role") === 'director'){
    // reverse order of tangrams
    finalTangramURLs = tangramURLs.slice().reverse();
  }

const correct = round.get("selection") === target;

const tangramsToRender = finalTangramURLs.map((tangram, i) => (
  <Tangram
    key={tangram}
    tangram={tangram}
    tangram_num={i}
    round={round}
    stage={stage}
    game={game}
    player={player}
    players={players}
    target={target}
    preloadedImage={preloadedImages[tangram]?.src}
  />
));

let feedback = '';

if (stage.get('name') == 'feedback') {
  if (round.get('selection') == '') {
    if (player.get('role') == 'director') {
      feedback = "Oops! Your partner did not respond in time."
    } else {
      feedback = "Oops! You did not respond in time."
    }
    
  } else {
    if (correct) {
      feedback = "Correct! You earned $0.03 cents!"
    } else {
      feedback = "Oops, that wasn't the target! You earned no bonus this round."
    }
  }
} else {
  feedback = '';
};


  return (

    <div className="task">
      <div className="board">
        <div className="header" style={{display:'flex', flexDirection: 'column', alignItems: 'center'}}>
          <h2 className="roleIndicator" style={{'float': 'center', 'marginLeft': '50px', fontSize: '20px'}}> You are the <b>{player.get('role')}</b>.</h2>
          {feedback !== '' ? (
            <h2 className="feedbackIndicator" style={{'float': 'center', 'marginLeft': '50px', fontSize: '20px'}}> {feedback}</h2>
          ) : (
            <div style={{height: '20px'}}></div>
          )}
          
        </div>
        <div className="all-tangrams">
          <div className="tangrams grid">
            {tangramsToRender}
          </div>
        </div>
      </div>
    </div>
  );
}

import { useStageTimer } from "@empirica/core/player/classic/react";
import React from "react";
import _ from "lodash";
import { useGame, useStage } from "@empirica/core/player/classic/react";

export function Tangram(props){
  const handleClick = e => {
    //console.log('click2')
    const { tangram, tangram_num, stage, player, players, round } = props;
    const partnerID = player.get('partner');
    const partner = players.filter((p) => p.id == partnerID)[0];
    const speakerMsgs = _.filter(round.get("chat"), msg => {
      return msg.sender.id == player.get('partner') && partner.get("role") == 'director'
    })

    // only register click for listener and only after the speaker has sent a message
    if (stage.get("name") == 'selection' &
        speakerMsgs.length > 0 &
        player.get('clicked') == '' &
        player.get('role') == 'matcher') {
      player.set("clicked", tangram)
      partner.set("clicked", tangram)
      player.stage.set("submit", true)
      partner.stage.set("submit", true)
    }
  };
  
  const { tangram, round, tangram_num, stage, player, game, target, ...rest } = props;

  const tangramurl = tangram
  const row = 1 + Math.floor(tangram_num / 2)
  const column = 1 + tangram_num % 2
  const mystyle = {
    "background" : "url(" + tangramurl + ")",
    "backgroundSize": "90%",
    "backgroundRepeat": "no-repeat",
    "backgroundPosition": "center",
    "width" : "25vh",
    "height" : "25vh",
    "gridRow": row,
    "gridColumn": column,
    "marginLeft": "15px",
    "marginRight": "15px",
    "marginTop": "15px",
    "marginBottom": "15px"
  };
  
if (tangram == target) {
  // selection stage highlight for speaker only
  if (stage.get("name") == "selection"){
    // if speaker and hasnt clicked yet...
    if(player.get('role') == 'director' &&
       (player.get('clicked') == '')) {
      
      _.extend(mystyle, {
        "outline" : "10px solid #000",
        "zIndex" : "9"
      }) 
    }
  }
  if (stage.get("name") == "feedback") {
    if (player.get("clicked") == tangram) {
      _.extend(mystyle, {
        "outline" : "10px solid green",
        "zIndex" : "9"
      })
    } else {
      if (player.get("clicked") !== '') {

      _.extend(mystyle, {
        "outline" : "10px solid red",
        "zIndex" : "9"
      })}
    }
  }
}

  // Highlight target object for speaker at selection stage
  // Show it to both players at feedback stage if 'showNegativeFeedback' enabled.
/*   if(tangram == target) {
    //console.log(player.get('clicked'));
    if(player.get('role') == 'director' &&
       (player.get('clicked') == '')) {
      
      _.extend(mystyle, {
        "outline" : "10px solid #000",
        "zIndex" : "9"
      })
    }
    if(player.get('role') == 'director' &&
       !game.get('showNegativeFeedback') &&
       player.get('clicked') != '') {
      _.extend(mystyle, {
        "outline" : "10px solid red",
        "zIndex" : "9"
      })
    }
  }
  

  // Highlight clicked object in green if correct;
  // If 'showNegativeFeedback' enabled, also show red if incorrect
  if(tangram == player.get('clicked')) {
    
    const color = (
      tangram == target ? '10px solid green' : (
        player.get('role') == 'matcher' || game.get('showNegativeFeedback')
      ) ? '10px solid red' : 'none'
    );
    _.extend(mystyle, {
      "outline" :  color,
      "zIndex" : "9"
    })
  } */

  return (
    <div
      onClick={handleClick}
      style={mystyle}
    >
    </div>
  );
}

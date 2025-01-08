import React from "react";
import { Button } from "../components/Button";


export function Consent({ next }) {
  return (
    <div className="flex items-center justify-center w-screen">
      <div className="w-1/2 mt-3 sm:mt-5 p-20">
        <h3 className="text-lg leading-6 font-medium text-gray-900">Consent</h3>
        <div className="instructions">
          <div className="smallimage">
            <center>
              <img width="300px" src="./madison.png" alt="Madison" />
            </center>
          </div>
          <p>
            Please read this consent agreement carefully before deciding whether to
            participate in this experiment. 
          </p><br/>
          <p>
            <strong>Description:</strong> You are invited to participate in a research study about language and communication. The purpose of the research is to understand how you interact and communicate with other people in naturalistic set-tings as a fluent English speaker. This research will be conducted through the Prolific platform, in-cluding participants from the US, UK, and Canada. If you decide to participate in this research, you will play a communication game in a group with one or more partners. 
          </p> <br/>
          <p>
            <strong>Time Involvement:</strong> The task will last the amount of time advertised on Prolific. You are free to withdraw from the study at any time. 
          </p><br/>
          <p>
            <strong>Risks and Benefits:</strong> You may become frustrated if your partner gets distracted, or experience discomfort if other partici-pants in your group send text that is inappropriate for the task. We ask you to please be respectful of other participants you might be interacting with to mitigate these risks. You may also experience dis-comfort when being asked to discuss or challenge emotionally salient political beliefs. Study data will be stored securely, in compliance with Stanford University standards, minimizing the risk of confiden-tiality breach. This study advances our scientific understanding of how people communication and collaborate in naturalistic settings. This study may lead to further insights about what can go wrong in teamwork, suggest potential interventions to overcome these barriers, and help to develop assistive technologies that collaborate with human partners. We cannot and do not guarantee or promise that you will receive any benefits from this study. 
          </p><br/>
          <p>
            <strong>Compensation:</strong> You will receive payment in the amount advertised on Prolific. If you do not complete this study, you will receive prorated payment based on the time that you have spent. Additionally, you may be eligible for bonus payments as described in the instructions. 
          </p><br/>
          <p>
            <strong>Participant's Rights:</strong> If you have read this form and have decided to participate in this project, please understand your participation is voluntary and you have the right to withdraw your consent or discontinue participation at any time without penalty or loss of benefits to which you are otherwise entitled. The alternative is not to participate. You have the right to refuse to answer particular questions. The results of this research study may be presented at scientific or professional meetings or published in scientific journals. Your individual privacy will be maintained in all published and writ-ten data resulting from the study. In accordance with scientific norms, the data from this study may be used or shared with other researchers for future research (after removing personally identifying information) without additional consent from you. 
          </p><br/>
          <p>
            <strong>Contact Information:</strong> If you have any questions, concerns or complaints about this research, its procedures, risks and benefits, contact the Protocol Director, Robert Hawkins (<a href="mailto:rdhawkins@stanford.edu">rdhawkins@stanford.edu</a>, 217-549-6923).
          </p><br/>
          <p>
            <strong>Independant Contact:</strong> If you are not satisfied with how this study is being conducted, or if you have any concerns, com-plaints, or general questions about the research or your rights as a participant, please contact the Stanford Institutional Review Board (IRB) to speak to someone independent of the research team at 650-723-2480 or toll free at 1-866-680-2906, or email at irbnonmed@stanford.edu. You can also write to the Stanford IRB, Stanford University, 1705 El Camino Real, Palo Alto, CA 94306. Please save or print a copy of this page for your records. 
          </p><br/>
          <p>
            <strong>If you agree to participate in this research, please click "Next"</strong>
          </p><br/>
        </div>
        <Button handleClick={next} autoFocus>
          <p>Next</p>
        </Button>
      </div>
    </div>
  );
}

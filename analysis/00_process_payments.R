library(tidyverse)

target_experiment_name <- "run_v3/18-1"

target_demo_folder <- here("data/raw_data", target_experiment_name)

processed_data_folder <- here("data/processed_data", target_experiment_name)

d_players <- read_csv(here(processed_data_folder, "players.csv"))
d_game <- read_csv(here(processed_data_folder, "games.csv"))
d_round <- read_csv(here(processed_data_folder, "rounds.csv"))

d_players |> 
  left_join(d_round |> 
              left_join(d_game) |> 
              group_by(gameID) |> 
              summarize(n_correct = sum(correct))) |> 
  select(prolificID, n_correct, bonus) |> 
  mutate(correct_bonus = round(n_correct* 0.03125, 2)) |>  
  filter(!is.na(correct_bonus) & correct_bonus > 0) |> 
  select(prolificID, bonus = correct_bonus) |> 
  write_csv(here(processed_data_folder, "player_bonuses.csv"))

d_players |> select(prolificID, bonus) |>  filter(!is.na(bonus) & bonus > 0) |> write_csv(here(processed_data_folder, "player_bonuses.csv"))

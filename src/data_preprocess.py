from datetime import timedelta, timezone
from typing import Set

import pandas as pd

from src.const import CLEANED_DATA_PATH, CON, RAW_DATA_PATH, TEAM_LIST

# host_cities.csv spells the host countries as FIFA-style codes; map them to the
# team-name spelling used in TEAM_LIST so a venue's country can be compared to the
# teams playing there (Canada/Mexico already match).
HOST_COUNTRY_NAMES = {"USA": "United States", "Canada": "Canada", "Mexico": "Mexico"}


def _attach_host_country(match_df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``host_country`` column from each match's venue city.

    Joins ``host_cities.csv`` on ``city_id`` so the simulation knows which country
    a match is played in, and can therefore tell when a host nation is playing at
    home (and deserves the Elo home-advantage bonus).
    """
    match_df = match_df.copy()
    cities = pd.read_csv(f"{RAW_DATA_PATH}/host_cities.csv")
    city_country = dict(zip(cities["id"], cities["country"].map(HOST_COUNTRY_NAMES)))
    match_df["host_country"] = match_df["city_id"].map(city_country)
    return match_df


def _save_sparse_teams(sparse_teams: Set[str]):
    with open(f"{CLEANED_DATA_PATH}/sparse_teams.txt", "w") as f:
        for team in sorted(sparse_teams):
            f.write(team + "\n")


def filter_historical_matches(
    df_raw: pd.DataFrame,
    team_list: list[str] = TEAM_LIST,
    start_date: str = "2016-01-01",
) -> pd.DataFrame:
    """Filter the raw Kaggle results to the modelling population.

    ``team_list`` (default the 48 WC2026 teams) and ``start_date`` are
    parameterised so a backtest can broaden coverage to the legacy 2018/2022
    participants and reach further back (e.g. 2014) for a fair training window.
    """
    df_raw = df_raw[df_raw["date"] >= start_date]
    df_raw = df_raw[
        (df_raw["home_team"].isin(team_list)) | (df_raw["away_team"].isin(team_list))
    ]

    tournament_include = [
        "World Cup",
        "European Championship",
        "Copa América",
        "African Nations Cup",
        "Asian Cup",
        "CONCACAF Championship",
        "Oceania Nations Cup",
    ]

    df = df_raw[df_raw["neutral"] | df_raw["tournament"].isin(tournament_include)]

    team_counts = (
        pd.concat([df["home_team"], df["away_team"]])
        .loc[lambda s: s.isin(team_list)]
        .value_counts()
    )

    print(f"Teams found: {len(team_counts)}/{len(team_list)}\n")
    print(team_counts.sort_values().to_string())
    sparse_teams = set(team_counts[team_counts < 15].index)
    print(f"Sparse teams: {sparse_teams}")

    _save_sparse_teams(sparse_teams)

    # Keep ALL UEFA Nations League games (every tier/division) for every team, not
    # just the originally-detected sparse ones: the adaptive per-team training filter
    # (src/backtest.py) decides downstream whether a team is sparse enough to use them,
    # and it must have the data available regardless of the window it picks. A prefix
    # match covers all divisions (A, B, C, D, and the A/B…C/D promotion labels).
    is_nations_league = df_raw["tournament"].str.startswith("European Nations League")

    df = df_raw[
        (df_raw["neutral"])
        | (df_raw["tournament"].isin(tournament_include))
        | is_nations_league
    ]

    df = df.drop(columns=["retrieved_date"])
    output_path = f"{CLEANED_DATA_PATH}/filtered_matches.csv"
    df.to_csv(output_path, index=False)
    print(f"Cleaned historical matches output to {output_path}.")

    team_counts = (
        pd.concat([df["home_team"], df["away_team"]])
        .loc[lambda s: s.isin(team_list)]
        .value_counts()
    )

    print(f"Teams found: {len(team_counts)}/{len(team_list)}\n")
    print(team_counts.sort_values().to_string())

    return df


def append_historical_elo(
    historical_matches_df: pd.DataFrame, historical_elo_df: pd.DataFrame
) -> pd.DataFrame:
    historical_matches_df["date"] = pd.to_datetime(historical_matches_df["date"])
    historical_elo_df["date"] = pd.to_datetime(historical_elo_df["date"])
    historical_matches_df = historical_matches_df.sort_values("date")
    historical_elo_df = historical_elo_df.sort_values("date")

    # Home team
    historical_matches_df = pd.merge_asof(
        historical_matches_df,
        historical_elo_df.rename(columns={"team": "home_team", "rating": "home_elo"}),
        on="date",
        by="home_team",
    )

    # Away team
    historical_matches_df = pd.merge_asof(
        historical_matches_df,
        historical_elo_df.rename(columns={"team": "away_team", "rating": "away_elo"}),
        on="date",
        by="away_team",
    )

    historical_matches_df.to_csv(f"{CLEANED_DATA_PATH}/matches.csv", index=False)
    CON.log(historical_matches_df.head())
    return historical_matches_df


def format_wc26_teams_dataset():
    """Format the wc26_teams.csv with the appropriate country names manually."""
    df = pd.read_csv(f"{RAW_DATA_PATH}/wc26_teams.csv")
    df = df.replace(
        [
            "Winner UEFA Playoff A",
            "Winner UEFA Playoff B",
            "Winner UEFA Playoff C",
            "Winner UEFA Playoff D",
            "Winner FIFA Playoff 1",
            "Winner FIFA Playoff 2",
            "USA",
            "IR Iran",
            "Cabo Verde",
            "Côte d'Ivoire",
        ],
        [
            "Bosnia and Herzegovina",
            "Sweden",
            "Turkey",
            "Czechia",
            "DR Congo",
            "Iraq",
            "United States",
            "Iran",
            "Cape Verde",
            "Ivory Coast",
        ],
    )
    print(df[~df["team_name"].isin(TEAM_LIST)])
    file_path = f"{CLEANED_DATA_PATH}/wc26_teams.csv"
    df.to_csv(file_path, index=False)
    CON.log(f"Formatted wc26_teams.csv. Output at {file_path}.")


def format_wc26_groupstage_matches_dataset():
    """Format wc26_groupstage_matches.csv with the actual country team names."""
    match_df = pd.read_csv(f"{RAW_DATA_PATH}/wc26_matches.csv")
    match_df = match_df[match_df["match_label"].str.contains("Group")]
    match_df = _attach_host_country(match_df)
    team_df = pd.read_csv(
        f"{CLEANED_DATA_PATH}/wc26_teams.csv"
    )  # use cleaned team dataset.

    match_df = pd.merge(
        match_df,
        team_df.rename(columns={"team_name": "home_team", "id": "home_team_id"}),
        on="home_team_id",
    )
    match_df = pd.merge(
        match_df,
        team_df.rename(columns={"team_name": "away_team", "id": "away_team_id"}),
        on="away_team_id",
    )
    match_df.drop(
        columns=[
            "id",
            "home_team_id",
            "away_team_id",
            "city_id",
            "stage_id",
            "fifa_code_x",
            "group_letter_x",
            "is_placeholder_x",
            "fifa_code_y",
            "group_letter_y",
            "is_placeholder_y",
        ],
        inplace=True,
    )
    file_path = f"{CLEANED_DATA_PATH}/wc26_groupstage_matches.csv"
    match_df.to_csv(file_path, index=False)
    CON.log(f"Formatted wc26 group stage matches. Output to {file_path}.")


def format_wc26_knockout_matches_dataset():
    match_df = pd.read_csv(f"{RAW_DATA_PATH}/wc26_matches.csv")
    knockout_df = match_df[~match_df["match_label"].str.contains("Group")]
    knockout_df = _attach_host_country(knockout_df)
    knockout_df.drop(
        columns=["id", "home_team_id", "away_team_id", "city_id"], inplace=True
    )
    file_path = f"{CLEANED_DATA_PATH}/wc26_knockout_matches.csv"
    knockout_df.to_csv(file_path, index=False)
    CON.log(f"Formatted wc26 knockout stage matches. Output to {file_path}.")


def change_timezone():
    df = pd.read_csv(f"{RAW_DATA_PATH}/wc26_matches.csv")
    naive = pd.to_datetime(
        df["kickoff_at"].str[:19], format="%Y-%m-%d %H:%M:%S"
    )  # parse wall-clock, ignore tag
    df["kickoff_at"] = (
        naive.dt.tz_localize(timezone(timedelta(hours=-4)))
        .dt.tz_convert("Asia/Hong_Kong")
        .dt.tz_localize(None)
    )
    df.to_csv(f"{RAW_DATA_PATH}/wc26_matches.csv", index=False)

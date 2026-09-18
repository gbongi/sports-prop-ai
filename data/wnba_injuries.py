import requests
from datetime import datetime


INJURY_URL = (
    "https://site.api.espn.com/apis/site/v2/"
    "sports/basketball/wnba/injuries"
)


def get_wnba_injuries():

    try:

        response = requests.get(
            INJURY_URL,
            timeout=10
        )

        response.raise_for_status()

        return response.json()

    except Exception as error:

        print(
            "Could not retrieve WNBA injuries:",
            error
        )

        return None


def parse_injuries(data):

    injuries = []

    if not data:
        return injuries

    for team_data in data.get("injuries", []):

        team = team_data.get("displayName", "Unknown")

        for injury in team_data.get("injuries", []):

            athlete = injury.get(
                "athlete",
                {}
            )

            player = athlete.get(
                "displayName",
                "Unknown"
            )

            status = injury.get(
                "status",
                "Unknown"
            )

            details = injury.get(
                "details",
                {}
            )

            injury_type = details.get(
                "type",
                "Unknown"
            )

            detail = details.get(
                "detail",
                ""
            )

            injuries.append(
                {
                    "team": team,
                    "player": player,
                    "status": status,
                    "injury": injury_type,
                    "detail": detail
                }
            )

    return injuries


def display_injuries(injuries):

    print()
    print("=" * 60)
    print("CURRENT WNBA INJURY REPORT")
    print("=" * 60)

    if not injuries:

        print(
            "No injury data returned."
        )

        return

    for injury in injuries:

        print()

        print(
            injury["player"],
            "|",
            injury["team"]
        )

        print(
            "Status:",
            injury["status"]
        )

        print(
            "Injury:",
            injury["injury"]
        )

        if injury["detail"]:

            print(
                "Detail:",
                injury["detail"]
            )


if __name__ == "__main__":

    print(
        "Checking WNBA injury report..."
    )

    data = get_wnba_injuries()

    injuries = parse_injuries(
        data
    )

    display_injuries(
        injuries
    )

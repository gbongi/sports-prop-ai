def derived_props(points, rebounds, assists):
    return {
        'pra': points + rebounds + assists,
        'ra': rebounds + assists,
        'pa': points + assists,
        'pr': points + rebounds,
    }

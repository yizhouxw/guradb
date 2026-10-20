"""Fixture-private group/member validation; no production split/selection calls."""


def validate_training(documents, rows, views, fragments, feature_parents, require, identity):
    grouping = documents['groups']
    groups, membership, cluster_split, content_split = {}, {}, {}, {}
    assets = {identity(a, ('asset_id', 'asset_version')): a for a in documents['assets']}
    for group in grouping['groups']:
        name = group['group_id']
        require(name not in groups, 'duplicate_group', name)
        require(group['split'] in ('train', 'validation', 'test'), 'invalid_split', name)
        groups[name] = group
        for member in group['members']:
            key = identity(member)
            require(key in rows and key not in membership, 'invalid_group_member', str(key))
            membership[key] = name
    # Check duplicate isolation from declared record groups before reconciling membership.
    # This catches mirror-source duplicates even when logical record IDs differ.
    for key, row in rows.items():
        require(row['group_id'] in groups, 'invalid_group_member', str(key))
        split = groups[row['group_id']]['split']
        cluster = row['duplicate_cluster']
        require(cluster not in cluster_split or cluster_split[cluster] == split,
                'cross_split_duplicate', cluster)
        cluster_split[cluster] = split
        if row['text_asset'] is not None:
            content_hash = assets[identity(row['text_asset'], ('asset_id', 'asset_version'))]['sha256']
            require(content_hash not in content_split or content_split[content_hash] == split,
                    'cross_split_duplicate', 'independent exact content digest')
            content_split[content_hash] = split
    require(set(membership) == set(rows), 'invalid_group_member', 'incomplete groups')
    for key, row in rows.items():
        require(membership[key] == row['group_id'], 'invalid_group_member', str(key))
    record_families = {}
    for key, group in membership.items():
        require(key[0] not in record_families or record_families[key[0]] == group,
                'cross_split_version', key[0])
        record_families[key[0]] = group
    training = documents['training']
    require(training['view_id'] in {v[0] for v in views}, 'invalid_view', training['view_id'])
    visible = {identity(r) for r in views[(training['view_id'],)]['records']}
    space = documents['features']
    recipe = training['recipe']
    identity(recipe, ('recipe_id', 'recipe_version'))
    require(all(recipe[name] == space[name] for name in ('space_id', 'model_version', 'dimension')),
            'wrong_feature_space', 'recipe')
    sample_ids = set()
    for sample in training['samples']:
        sample_key = identity(sample, ('sample_id', 'sample_version'))
        require(sample_key[0] not in sample_ids, 'duplicate_sample', str(sample_key))
        sample_ids.add(sample_key[0])
        require(sample['group_id'] in groups and sample['split'] == groups[sample['group_id']]['split'],
                'cross_split_member', sample['sample_id'])
        members = sample['members']
        require(sorted(m['role'] for m in members) == ['image', 'negative', 'positive', 'query'],
                'invalid_sample_roles', sample['sample_id'])
        for member in members:
            key = identity(member['record'])
            require(key in visible, 'wrong_member_version', str(key))
            require(membership[key] == sample['group_id'], 'cross_split_member', str(key))
            fragment_key = identity(member, ('fragment_id', 'fragment_version'))
            require(fragment_key in fragments and identity(fragments[fragment_key]['parent']) == key,
                    'wrong_member_version', str(fragment_key))
            row = rows[key]
            if member['role'] == 'image':
                require(row['image_asset'] is not None and fragments[fragment_key]['kind'] == 'image_xywh',
                        'missing_modality', str(key))
            else:
                require(row['text_asset'] is not None and key in feature_parents and
                        fragments[fragment_key]['kind'] == 'text_utf8_bytes', 'missing_modality', str(key))
        distinct = {identity(m['record']) for m in members if m['role'] != 'image'}
        require(len(distinct) == 3, 'invalid_sample_roles', 'query/positive/negative must differ')
        positive = next(m for m in members if m['role'] == 'positive')
        image = next(m for m in members if m['role'] == 'image')
        require(positive['record'] == image['record'], 'invalid_sample_roles', 'positive image association')
    expected_missing = {key for key in visible if rows[key]['text_asset'] is None or key not in feature_parents}
    declared_missing = [identity(item['record']) for item in training['excluded']]
    require(len(declared_missing) == len(set(declared_missing)) and set(declared_missing) == expected_missing and
            all(item['reason'] == 'missing_text_image_and_vector' for item in training['excluded']),
            'unreported_missing_modality', 'explicit exclusion set')

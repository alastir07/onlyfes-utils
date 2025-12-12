"""
GitHub Pages Leaderboard Module
Generates and deploys EP leaderboard HTML to GitHub Pages
"""

import os
import subprocess
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import logging

log = logging.getLogger('ClanBot')


def generate_leaderboard_html(lifetime_data, big_spender_data, raffle_data, template_path='leaderboard_template.html'):
    """
    Generate HTML for the leaderboard from member data
    
    Args:
        lifetime_data: List of dicts with 'rsn', 'lifetime_ep', 'rank_id', and 'rank_name' keys

        big_spender_data: List of dicts with 'rsn', 'total_spent', 'rank_id', and 'rank_name' keys
        raffle_data: List of dicts with 'rsn', 'raffle_entries', 'rank_id', and 'rank_name' keys
        template_path: Path to the HTML template file
    
    Returns:
        str: Generated HTML content
    """
    # Read template
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    # Get the directory containing rank icons
    rank_icons_dir = Path(template_path).parent / 'clan-rank-icons'
    
    def generate_rows(members_data, ep_key):
        """Helper function to generate table rows"""
        rows = []
        for rank, member in enumerate(members_data, start=1):
            rsn = member['rsn']
            ep = member[ep_key]
            rank_id = member.get('rank_id', '')
            rank_name = member.get('rank_name', '')
            
            # Build rank icon HTML if rank info exists AND icon file exists
            rank_icon_html = ''
            if rank_id and rank_name:
                # Try to find the icon file (case-insensitive)
                icon_pattern = f"{rank_id} - {rank_name}.png"
                icon_path = rank_icons_dir / icon_pattern
                
                # If exact match doesn't exist, try case-insensitive search
                if not icon_path.exists() and rank_icons_dir.exists():
                    for file in rank_icons_dir.iterdir():
                        if file.name.lower() == icon_pattern.lower():
                            icon_pattern = file.name  # Use the actual filename
                            icon_path = file
                            break
                
                if icon_path.exists():
                    rank_icon_html = f'<img src="clan-rank-icons/{icon_pattern}" alt="{rank_name}" class="rank-icon">'
            
            row = f'''                    <tr>
                        <td class="rank-cell">{rank}</td>
                        <td class="name-cell">{rank_icon_html}{rsn}</td>
                        <td class="ep-cell">{ep:,}</td>
                    </tr>'''
            rows.append(row)
        return '\n'.join(rows)
    
    # Generate rows for both leaderboards
    lifetime_rows = generate_rows(lifetime_data, 'lifetime_ep')
    big_spender_rows = generate_rows(big_spender_data, 'total_spent')
    raffle_rows = generate_rows(raffle_data, 'raffle_entries')
    
    # Replace placeholders
    last_updated = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    html = template.replace('{{LAST_UPDATED}}', last_updated)
    html = html.replace('{{PAGE_TITLE}}', '🏆 All-Time Event Points Leaderboard 🏆')
    html = html.replace('{{LIFETIME_ROWS}}', lifetime_rows)
    html = html.replace('{{BIGSPENDER_ROWS}}', big_spender_rows)
    html = html.replace('{{RAFFLE_ROWS}}', raffle_rows)
    
    return html



def deploy_to_github_pages(html_content, github_token, repo_owner='alastir07', repo_name='onlyfes-utils'):
    """
    Deploy HTML content to GitHub Pages (gh-pages branch)
    
    Args:
        html_content: The generated HTML string
        github_token: GitHub personal access token
        repo_owner: GitHub username
        repo_name: Repository name
    
    Returns:
        bool: True if successful, False otherwise
    """
    repo_url = f'https://{github_token}@github.com/{repo_owner}/{repo_name}.git'
    
    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            log.info(f"Cloning gh-pages branch to {temp_dir}")
            
            # Clone only the gh-pages branch (or create it if it doesn't exist)
            result = subprocess.run(
                ['git', 'clone', '--branch', 'gh-pages', '--single-branch', repo_url, temp_dir],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # If gh-pages doesn't exist, create it
            if result.returncode != 0:
                log.warning(f"Failed to clone gh-pages branch. Error: {result.stderr}")
                log.info("Attempting to create gh-pages branch from scratch")
                subprocess.run(['git', 'clone', repo_url, temp_dir], check=True, timeout=30)
                subprocess.run(['git', 'checkout', '--orphan', 'gh-pages'], cwd=temp_dir, check=True)
                subprocess.run(['git', 'rm', '-rf', '.'], cwd=temp_dir, check=True)
            else:
                log.info("Successfully cloned gh-pages branch")
            
            # Write HTML file
            html_path = Path(temp_dir) / 'event-points-leaderboard.html'
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Copy assets if they don't exist
            assets_source = Path(__file__).parent
            assets = ['scroll_top.gif', 'scroll_middle.gif', 'scroll_bottom.gif', 'bg2.jpg', 'runescape.ttf', 'bond.png']
            
            for asset in assets:
                source_path = assets_source / asset
                dest_path = Path(temp_dir) / asset
                if source_path.exists() and not dest_path.exists():
                    shutil.copy(source_path, dest_path)
                    log.info(f"Copied {asset} to gh-pages")
            
            # Copy rank icons directory (always refresh to ensure new icons are deployed)
            rank_icons_source = assets_source / 'clan-rank-icons'
            rank_icons_dest = Path(temp_dir) / 'clan-rank-icons'
            if rank_icons_source.exists():
                # Remove existing directory if present
                if rank_icons_dest.exists():
                    shutil.rmtree(rank_icons_dest)
                # Copy fresh
                shutil.copytree(rank_icons_source, rank_icons_dest)
                log.info(f"Copied clan-rank-icons directory to gh-pages")
            
            # Configure Git user (required for commits)
            subprocess.run(['git', 'config', 'user.email', 'bot@onlyfes.com'], cwd=temp_dir, check=True)
            subprocess.run(['git', 'config', 'user.name', 'OnlyFEs Bot'], cwd=temp_dir, check=True)
            
            # Git operations
            subprocess.run(['git', 'add', '.'], cwd=temp_dir, check=True)
            
            # Check if there are changes to commit
            status = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True,
                cwd=temp_dir,
                check=True
            )
            
            if status.stdout.strip():
                subprocess.run(
                    ['git', 'commit', '-m', f'Update leaderboard - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'],
                    cwd=temp_dir,
                    check=True
                )
                subprocess.run(['git', 'push', 'origin', 'gh-pages', '--force'], cwd=temp_dir, check=True, timeout=30)
                log.info("Successfully deployed to GitHub Pages")
                return True
            else:
                log.info("No changes to deploy")
                return True
                
        except subprocess.TimeoutExpired:
            log.error("Git operation timed out")
            return False
        except subprocess.CalledProcessError as e:
            log.error(f"Git operation failed: {e}")
            return False
        except Exception as e:
            log.error(f"Deployment error: {e}")
            return False


def update_leaderboard(supabase, github_token):
    """
    Main function to fetch data, generate HTML, and deploy
    
    Args:
        supabase: Supabase client instance
        github_token: GitHub personal access token
    
    Returns:
        tuple: (success: bool, message: str)
    """
    def fetch_all_rows(query_builder, page_size=1000):
        """Helper to fetch all rows using pagination"""
        all_data = []
        page = 0
        while True:
            start = page * page_size
            end = start + page_size - 1
            # Note: Supabase range is inclusive
            response = query_builder.range(start, end).execute()
            data = response.data
            
            if not data:
                break
                
            all_data.extend(data)
            
            if len(data) < page_size:
                break
                
            page += 1
        return all_data

    try:
        log.info("Fetching leaderboard data...")
        
        # Fetch Lifetime Leaderboard data (sum of positive modifications)
        log.info("Fetching Lifetime leaderboard data...")
        
        # Fetch all positive transactions with member data
        # Note: We can't filter on nested fields when using explicit relationship names,
        # so we'll filter in Python instead
        lifetime_query = supabase.table('event_point_transactions') \
            .select('member_id, modification, members!event_point_transactions_member_id_fkey(status, current_rank_id, member_rsns(rsn, is_primary), ranks!current_rank_id(id, name))') \
            .gt('modification', 0)
            
        lifetime_transactions_data = fetch_all_rows(lifetime_query)

        # Aggregate lifetime EP by member (filter in Python)
        lifetime_dict = {}
        for txn in lifetime_transactions_data:
            member_id = txn['member_id']
            member_data = txn.get('members')
            
            # Skip if no member data or member is not active
            if not member_data or member_data.get('status') != 'Active':
                continue
            
            # Get primary RSN
            member_rsns = member_data.get('member_rsns', [])
            if not member_rsns:
                continue
            
            primary_rsn = None
            for rsn_entry in member_rsns:
                if rsn_entry.get('is_primary'):
                    primary_rsn = rsn_entry.get('rsn')
                    break
            
            if not primary_rsn:
                continue
            
            # Initialize member in dict if not exists
            if member_id not in lifetime_dict:
                rank_info = member_data.get('ranks') or {}
                
                lifetime_dict[member_id] = {
                    'rsn': primary_rsn,
                    'lifetime_ep': 0,
                    'rank_id': rank_info.get('id', ''),
                    'rank_name': rank_info.get('name', '')
                }
            
            lifetime_dict[member_id]['lifetime_ep'] += txn['modification']

        
        # Convert to list and sort
        lifetime_data = sorted(lifetime_dict.values(), key=lambda x: x['lifetime_ep'], reverse=True)
        log.info(f"Found {len(lifetime_data)} members for Lifetime leaderboard")
        
        # Fetch Big Spender Leaderboard data (sum of negative modifications, excluding test)
        log.info("Fetching Big Spender leaderboard data...")
        big_spender_query = supabase.table('event_point_transactions') \
            .select('member_id, modification, reason, members!event_point_transactions_member_id_fkey(status, current_rank_id, member_rsns(rsn, is_primary), ranks!current_rank_id(id, name))') \
            .lt('modification', 0)
            
        big_spender_transactions_data = fetch_all_rows(big_spender_query)

        # Aggregate big spender EP by member (filter in Python, excluding test transactions)
        big_spender_dict = {}
        for txn in big_spender_transactions_data:
            # Skip if reason contains "test" (case-insensitive)
            reason = txn.get('reason', '') or ''
            if 'test' in reason.lower():
                continue
            
            member_id = txn['member_id']
            member_data = txn.get('members')
            
            # Skip if no member data or member is not active
            if not member_data or member_data.get('status') != 'Active':
                continue
            
            # Get primary RSN
            member_rsns = member_data.get('member_rsns', [])
            if not member_rsns:
                continue
            
            primary_rsn = None
            for rsn_entry in member_rsns:
                if rsn_entry.get('is_primary'):
                    primary_rsn = rsn_entry.get('rsn')
                    break
            
            if not primary_rsn:
                continue
            
            # Initialize member in dict if not exists
            if member_id not in big_spender_dict:
                rank_info = member_data.get('ranks') or {}
                
                big_spender_dict[member_id] = {
                    'rsn': primary_rsn,
                    'total_spent': 0,
                    'rank_id': rank_info.get('id', ''),
                    'rank_name': rank_info.get('name', '')
                }
            
            # Add absolute value (convert negative to positive for display)
            big_spender_dict[member_id]['total_spent'] += abs(txn['modification'])

        
        # Convert to list and sort
        big_spender_data = sorted(big_spender_dict.values(), key=lambda x: x['total_spent'], reverse=True)
        log.info(f"Found {len(big_spender_data)} members for Big Spender leaderboard")

        # Fetch Raffle Leaderboard data (count of positive transactions in Dec 2025)
        log.info("Fetching Raffle leaderboard data...")
        raffle_query = supabase.table('event_point_transactions') \
            .select('member_id, modification, date_enacted, members!event_point_transactions_member_id_fkey(status, current_rank_id, member_rsns(rsn, is_primary), ranks!current_rank_id(id, name))') \
            .gt('modification', 0) \
            .gte('date_enacted', '2025-12-01 00:00:00') \
            .lte('date_enacted', '2025-12-31 23:59:59')
            
        raffle_transactions_data = fetch_all_rows(raffle_query)

        # Aggregate raffle entries by member
        raffle_dict = {}
        for txn in raffle_transactions.data:
            member_id = txn['member_id']
            member_data = txn.get('members')
            
            # Skip if no member data or member is not active
            if not member_data or member_data.get('status') != 'Active':
                continue
            
            # Get primary RSN
            member_rsns = member_data.get('member_rsns', [])
            if not member_rsns:
                continue
            
            primary_rsn = None
            for rsn_entry in member_rsns:
                if rsn_entry.get('is_primary'):
                    primary_rsn = rsn_entry.get('rsn')
                    break
            
            if not primary_rsn:
                continue
            
            # Initialize member in dict if not exists
            if member_id not in raffle_dict:
                rank_info = member_data.get('ranks') or {}
                
                raffle_dict[member_id] = {
                    'rsn': primary_rsn,
                    'raffle_entries': 0,
                    'rank_id': rank_info.get('id', ''),
                    'rank_name': rank_info.get('name', '')
                }
            
            # Each transaction counts as 1 entry
            raffle_dict[member_id]['raffle_entries'] += 1
        
        # Convert to list and sort
        raffle_data = sorted(raffle_dict.values(), key=lambda x: x['raffle_entries'], reverse=True)
        log.info(f"Found {len(raffle_data)} members for Raffle leaderboard")
        
        # Generate HTML
        template_path = Path(__file__).parent / 'leaderboard_template.html'
        html = generate_leaderboard_html(lifetime_data, big_spender_data, raffle_data, template_path)
        
        # Deploy to GitHub Pages
        success = deploy_to_github_pages(html, github_token)
        
        if success:
            url = "https://alastir07.github.io/onlyfes-utils/event-points-leaderboard.html"
            return (True, f"Leaderboard updated successfully! View at: {url}")
        else:
            return (False, "Failed to deploy to GitHub Pages")
            
    except Exception as e:
        log.error(f"Error updating leaderboard: {e}")
        return (False, f"Error: {str(e)}")


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


def generate_leaderboard_html(members_data, template_path='leaderboard_template.html'):
    """
    Generate HTML for the leaderboard from member data
    
    Args:
        members_data: List of dicts with 'rsn' and 'total_ep' keys
        template_path: Path to the HTML template file
    
    Returns:
        str: Generated HTML content
    """
    # Read template
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    # Generate table rows
    rows = []
    for rank, member in enumerate(members_data, start=1):
        rsn = member['rsn']
        ep = member['total_ep']
        row = f'''                    <tr>
                        <td class="rank-cell">{rank}</td>
                        <td class="name-cell">{rsn}</td>
                        <td class="ep-cell">{ep:,}</td>
                    </tr>'''
        rows.append(row)
    
    leaderboard_rows = '\n'.join(rows)
    
    # Replace placeholders
    last_updated = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    html = template.replace('{{LAST_UPDATED}}', last_updated)
    html = html.replace('{{LEADERBOARD_ROWS}}', leaderboard_rows)
    
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
                log.info("gh-pages branch doesn't exist, creating it")
                subprocess.run(['git', 'clone', repo_url, temp_dir], check=True, timeout=30)
                os.chdir(temp_dir)
                subprocess.run(['git', 'checkout', '--orphan', 'gh-pages'], check=True)
                subprocess.run(['git', 'rm', '-rf', '.'], check=True)
            else:
                os.chdir(temp_dir)
            
            # Write HTML file
            with open('index.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Copy assets if they don't exist
            assets_source = Path(__file__).parent
            assets = ['scroll_top.gif', 'scroll_middle.gif', 'scroll_bottom.gif', 'bg2.jpg', 'runescape.ttf']
            
            for asset in assets:
                source_path = assets_source / asset
                dest_path = Path(temp_dir) / asset
                if source_path.exists() and not dest_path.exists():
                    shutil.copy(source_path, dest_path)
                    log.info(f"Copied {asset} to gh-pages")
            
            # Git operations
            subprocess.run(['git', 'add', '.'], check=True)
            
            # Check if there are changes to commit
            status = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True,
                check=True
            )
            
            if status.stdout.strip():
                subprocess.run(
                    ['git', 'commit', '-m', f'Update leaderboard - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'],
                    check=True
                )
                subprocess.run(['git', 'push', 'origin', 'gh-pages', '--force'], check=True, timeout=30)
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
    try:
        # Fetch EP data
        log.info("Fetching EP leaderboard data...")
        response = supabase.table('members') \
            .select('total_ep, member_rsns!inner(rsn, is_primary)') \
            .eq('status', 'Active') \
            .gt('total_ep', 0) \
            .eq('member_rsns.is_primary', True) \
            .order('total_ep', desc=True) \
            .execute()
        
        members = response.data
        
        if not members:
            log.warning("No members with event points found")
            return (False, "No members with event points found")
        
        # Transform data for template
        members_data = [
            {
                'rsn': member['member_rsns'][0]['rsn'],
                'total_ep': member['total_ep']
            }
            for member in members
        ]
        
        log.info(f"Found {len(members_data)} members with event points")
        
        # Generate HTML
        template_path = Path(__file__).parent / 'leaderboard_template.html'
        html = generate_leaderboard_html(members_data, template_path)
        
        # Deploy to GitHub Pages
        success = deploy_to_github_pages(html, github_token)
        
        if success:
            url = "https://alastir07.github.io/onlyfes-utils/"
            return (True, f"Leaderboard updated successfully! View at: {url}")
        else:
            return (False, "Failed to deploy to GitHub Pages")
            
    except Exception as e:
        log.error(f"Error updating leaderboard: {e}")
        return (False, f"Error: {str(e)}")

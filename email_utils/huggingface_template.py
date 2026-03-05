def get_paper_block_html(title: str, rate: str, paper_id: str, summary: str, paper_url: str, upvotes: int = 0):
    block_template = """
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="font-family: Arial, sans-serif; border: 1px solid #ddd; border-radius: 8px; padding: 16px; background-color: #fff8e1;">
    <tr>
        <td style="font-size: 20px; font-weight: bold; color: #333;">
            {title}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #333; padding: 8px 0;">
            <strong>Relevance:</strong> {rate}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #333; padding: 8px 0;">
            <strong>Paper ID:</strong> {paper_id} | <strong>Upvotes:</strong> {upvotes}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #333; padding: 8px 0;">
            <strong>Summary:</strong> {summary}
        </td>
    </tr>
    <tr>
        <td style="padding: 8px 0;">
            <a href="{paper_url}" style="display: inline-block; text-decoration: none; font-size: 14px; font-weight: bold; color: #fff; background-color: #ff6f00; padding: 8px 16px; border-radius: 4px;">View Paper</a>
        </td>
    </tr>
</table>
"""
    return block_template.format(
        title=title, rate=rate, paper_id=paper_id, summary=summary, paper_url=paper_url, upvotes=upvotes
    )


def get_model_block_html(title: str, rate: str, model_id: str, summary: str, model_url: str, likes: int = 0, downloads: int = 0):
    if downloads >= 1000000:
        downloads_str = f"{downloads/1000000:.1f}M"
    elif downloads >= 1000:
        downloads_str = f"{downloads/1000:.1f}K"
    else:
        downloads_str = str(downloads)

    block_template = """
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="font-family: Arial, sans-serif; border: 1px solid #ddd; border-radius: 8px; padding: 16px; background-color: #e3f2fd;">
    <tr>
        <td style="font-size: 20px; font-weight: bold; color: #333;">
            {title}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #333; padding: 8px 0;">
            <strong>Usefulness:</strong> {rate}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #333; padding: 8px 0;">
            <strong>Model ID:</strong> {model_id} | <strong>Likes:</strong> {likes} | <strong>Downloads:</strong> {downloads_str}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #333; padding: 8px 0;">
            <strong>Summary:</strong> {summary}
        </td>
    </tr>
    <tr>
        <td style="padding: 8px 0;">
            <a href="{model_url}" style="display: inline-block; text-decoration: none; font-size: 14px; font-weight: bold; color: #fff; background-color: #1976d2; padding: 8px 16px; border-radius: 4px;">View Model</a>
        </td>
    </tr>
</table>
"""
    return block_template.format(
        title=title, rate=rate, model_id=model_id, summary=summary, model_url=model_url,
        likes=likes, downloads_str=downloads_str
    )

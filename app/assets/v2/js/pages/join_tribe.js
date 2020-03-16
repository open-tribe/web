const joinTribe = () => {
  $('[data-jointribe]').each(function(index, elem) {

    $(elem).on('click', function(e) {

      if (!document.contxt.github_handle) {
        e.preventDefault();
        _alert('Please login first.', 'error');
        return;
      }

      $(elem).attr('disabled', true);
      e.preventDefault();
      const tribe = $(elem).data('jointribe');
      const url = `/tribe/${tribe}/join/`;
      const sendJoin = fetchData (url, 'POST', {}, {'X-CSRFToken': $("input[name='csrfmiddlewaretoken']").val()});

      $.when(sendJoin).then(function(response) {
        $(elem).attr('disabled', false);
        $(elem).attr('member', response.is_member);
        response.is_member ? $(elem).html('Unfollow <i class="fas fa-minus"></i>') : $(elem).html('Follow <i class="fas fa-plus"></i>');
        let old_count = parseInt($('#follower_count span').text());
        var new_count = response.is_member ? old_count + 1 : old_count - 1;

        $('#follower_count span').fadeOut();
        setTimeout(function() {
          $('#follower_count span').text(new_count).fadeIn();
        }, 500);
      }).fail(function(error) {
        $(elem).attr('disabled', false);
      });

    });
  });
};

joinTribe();

const joinTribeDirect = (elem) => {

  if (!document.contxt.github_handle) {
    _alert('Please login first.', 'error');
    return;
  }

  $(elem).attr('disabled', true);
  const tribe = $(elem).data('jointribe');
  const url = `/tribe/${tribe}/join/`;
  const sendJoin = fetchData (url, 'POST', {}, {'X-CSRFToken': $("input[name='csrfmiddlewaretoken']").val()});

  $.when(sendJoin).then(function(response) {
    $(elem).attr('disabled', false);
    $(elem).attr('member', response.is_member);
    $(elem).attr('hidden', true);
  }).fail(function(error) {
    $(elem).attr('disabled', false);
  });
};


const tribeLeader = () => {
  $('[data-tribeleader]').each(function(index, elem) {

    $(elem).on('click', function() {
      $(elem).attr('disabled', true);

      const memberId = $(elem).data('tribeleader');
      const url = '/tribe/leader/';
      const template = '<span class="text-center text-uppercase font-weight-bold p-1 text-highlight-yellow">Tribe Leader</span>';

      const sendLeader = fetchData (url, 'POST', {'member': memberId}, {'X-CSRFToken': $("input[name='csrfmiddlewaretoken']").val()});

      $.when(sendLeader).then(function(response) {
        $(elem).after(template);
        $(elem).closest('.card').find('.badge-tribe_leader').removeClass('d-none');
        $(elem).remove();
      }).fail(function(error) {
        $(elem).attr('disabled', false);
      });

    });
  });
};

tribeLeader();
